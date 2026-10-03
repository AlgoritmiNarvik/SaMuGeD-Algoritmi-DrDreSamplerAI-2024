from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph

from samuged.dataset import file_digest
from scripts import make_paper


ROOT = Path(__file__).resolve().parents[1]


def test_documented_direct_script_entrypoint_imports():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/make_paper.py"), "--help"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--theme-input-audit" in completed.stdout
    assert "--closed-evaluation" in completed.stdout
    assert "--part-ranking-audit" in completed.stdout
    assert "--certified-drum-audit" in completed.stdout
    assert "--selection-external-evaluation" in completed.stdout


def _write(path: Path, value) -> None:
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _dataset(path: Path, *, run_key: str = "run-1", algorithm: str | None = None) -> Path:
    path.mkdir()
    _write(path / "sources.jsonl", '{"source_id":"one"}\n')
    _write(path / "phrases.jsonl", '{"phrase_id":"one"}\n')
    build = {"run_key": run_key, "config": {"lengths": [6, 8], "top_k": 3}}
    if algorithm:
        build["algorithm"] = algorithm
    _write(path / "build_config.json", build)
    summary = {
        "run_key": run_key,
        "source_manifest_sha256": file_digest(path / "sources.jsonl"),
        "phrase_manifest_sha256": file_digest(path / "phrases.jsonl"),
    }
    _write(path / "summary.json", summary)
    audit = {
        "passed": True,
        "failure_count": 0,
        "run_key": run_key,
        "source_manifest_sha256": file_digest(path / "sources.jsonl"),
        "phrase_manifest_sha256": file_digest(path / "phrases.jsonl"),
        "build_config_sha256": file_digest(path / "build_config.json"),
        "summary_sha256": file_digest(path / "summary.json"),
    }
    _write(path / "audit.json", audit)
    return path


def test_dataset_rejects_audit_copied_from_other_artifacts(tmp_path: Path) -> None:
    first = _dataset(tmp_path / "first")
    second = _dataset(tmp_path / "second")
    _write(second / "phrases.jsonl", '{"phrase_id":"different"}\n')
    (second / "audit.json").write_bytes((first / "audit.json").read_bytes())

    with pytest.raises(ValueError, match="current phrases.jsonl"):
        make_paper.validate_dataset(second)


def test_dataset_algorithm_comes_from_bound_build_config(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "dataset", algorithm="aligned_indexed")

    assert make_paper.validate_dataset(dataset)["algorithm"] == "aligned_indexed"


def test_full_scope_requires_explicit_source_coverage_audit(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "dataset")
    summary_path = dataset / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update({"source_files": 1, "discovered_source_files": 1, "cohort_limit": None})
    _write(summary_path, summary)
    audit_path = dataset / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["summary_sha256"] = file_digest(summary_path)
    audit["full_source_coverage_required"] = False
    _write(audit_path, audit)

    with pytest.raises(ValueError, match="full-scope dataset audit"):
        make_paper.validate_dataset(dataset)


def test_aligned_method_description_states_alignment_limits() -> None:
    title, text = make_paper.method_description(
        "aligned",
        {"min_notes": 6, "max_notes": 32, "max_edits": 4, "max_edit_fraction": 0.15},
    )

    assert title == "Aligned detector"
    assert "monotone alignment" in text
    assert "fixed transposition" in text
    assert "does not warp tempo" in text


def test_indexed_description_identifies_experimental_index() -> None:
    _title, text = make_paper.method_description(
        "aligned_indexed",
        {"min_notes": 6, "max_notes": 32, "max_edits": 4, "max_edit_fraction": 0.15},
    )

    assert "experimental index" in text
    assert "same verifier" in text


def test_nonzero_screening_cross_edges_are_rejected(monkeypatch, tmp_path: Path) -> None:
    screening = tmp_path / "screening"
    screening.mkdir()
    monkeypatch.setattr(
        make_paper,
        "verify_screening",
        lambda _dataset, _screening: {"retained_cross_split_candidate_edges": 1},
    )

    with pytest.raises(ValueError, match="retains cross split"):
        make_paper.validate_screening(tmp_path, screening)


def test_report_date_precedence_and_fail_closed(monkeypatch) -> None:
    receipt = {"started_at_utc": "2026-10-03T04:20:54+00:00"}
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert make_paper.resolve_report_date("2026-09-30", receipt) == ("2026-09-30", "explicit")
    assert make_paper.resolve_report_date(None, receipt) == ("1970-01-01", "SOURCE_DATE_EPOCH UTC")
    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    assert make_paper.resolve_report_date(None, receipt) == (
        "2026-10-03", "melodic experiment receipt UTC",
    )
    with pytest.raises(ValueError, match="report date is unavailable"):
        make_paper.resolve_report_date(None, None)


def test_invariant_pdf_is_byte_identical(tmp_path: Path) -> None:
    style = getSampleStyleSheet()["BodyText"]
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    make_paper._build_pdf(first, [Paragraph("Fixed evidence", style)])
    make_paper._build_pdf(second, [Paragraph("Fixed evidence", style)])

    assert first.read_bytes() == second.read_bytes()


def test_melodic_aggregate_tampering_is_detected(tmp_path: Path) -> None:
    source = ROOT / "research_local" / "evaluation_reference_v02"
    if not source.is_dir():
        pytest.skip("frozen melodic evaluation is not available")
    target = tmp_path / "evaluation"
    target.mkdir()
    for name in ("raw_results.json", "experiment_receipt.json", "source_snapshot.json"):
        shutil.copyfile(source / name, target / name)
    shutil.copytree(source / "source_snapshot", target / "source_snapshot")
    aggregate = json.loads((source / "aggregate.json").read_text(encoding="utf-8"))
    aggregate["methods"]["approximate"]["by_split"]["test"]["occurrence"]["f1"] = 0.0
    _write(target / "aggregate.json", aggregate)

    with pytest.raises(ValueError, match="differs from raw results"):
        make_paper.validate_melody(target / "aggregate.json")


def test_melody_does_not_accept_unbound_raw_and_aggregate(tmp_path):
    _write(tmp_path / "aggregate.json", {"case_count": 0})
    _write(tmp_path / "raw_results.json", {"cases": []})
    with pytest.raises(ValueError, match="requires a frozen experiment receipt"):
        make_paper.validate_melody(tmp_path / "aggregate.json")


def _frozen_copy(source: Path, tmp_path: Path, name: str) -> Path:
    if not source.is_dir():
        pytest.skip(f"frozen artifact is not available: {source}")
    target = tmp_path / name
    shutil.copytree(source, target)
    return target


def _rebind_completed_artifact(directory: Path, filename: str) -> None:
    completion_path = directory / "completion_receipt.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    artifact = directory / filename
    completion["artifacts"][filename] = {
        "sha256": file_digest(artifact),
        "bytes": artifact.stat().st_size,
    }
    _write(completion_path, completion)


def test_legacy_stress_validates_metadata_and_marks_provenance(tmp_path: Path) -> None:
    source = ROOT / "research_local" / "drum_stress_v01"
    target = _frozen_copy(source, tmp_path, "stress")

    aggregate, _inputs = make_paper.validate_stress(target / "aggregate.json")

    assert aggregate["provenance_status"] == "legacy_no_executable_snapshot"
    raw = json.loads((target / "raw_results.json").read_text(encoding="utf-8"))
    raw["cases"][0]["case_id"] = "forged-case-id"
    _write(target / "raw_results.json", raw)
    with pytest.raises(ValueError, match="metadata"):
        make_paper.validate_stress(target / "aggregate.json")


def test_external_rejects_code_snapshot_tampering(tmp_path: Path) -> None:
    source = ROOT / "research_local" / "jku_reference_v02"
    target = _frozen_copy(source, tmp_path, "jku")
    code = target / "provenance" / "samuged" / "evaluate_jku.py"
    code.write_bytes(code.read_bytes() + b"\n# tamper probe\n")

    with pytest.raises(ValueError, match="code snapshot hash"):
        make_paper.validate_external(target / "aggregate.json")


def test_external_rejects_missing_frozen_cohort_row(tmp_path: Path) -> None:
    source = ROOT / "research_local" / "jku_reference_v02"
    target = _frozen_copy(source, tmp_path, "jku")
    raw_path = target / "raw_results.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["results"].pop()
    _write(raw_path, raw)
    aggregate_path = target / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["groups"] = make_paper._jku_groups(raw["results"])
    aggregate["raw_results_sha256"] = file_digest(raw_path)
    _write(aggregate_path, aggregate)

    with pytest.raises(ValueError, match="row coverage"):
        make_paper.validate_external(aggregate_path)


def test_external_recomputes_published_metric_golden(tmp_path: Path) -> None:
    source = ROOT / "research_local" / "jku_reference_v02"
    target = _frozen_copy(source, tmp_path, "jku")
    published_path = target / "published_examples.json"
    published = json.loads(published_path.read_text(encoding="utf-8"))
    published["examples"]["algo1"]["scores"]["F"] = 123.456
    _write(published_path, published)
    aggregate_path = target / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["published_examples_sha256"] = file_digest(published_path)
    _write(aggregate_path, aggregate)

    with pytest.raises(ValueError, match="published golden"):
        make_paper.validate_external(aggregate_path)


def test_closed_evaluation_reconstructs_fresh_and_real_results() -> None:
    source = ROOT / "research_local" / "closed_patterns_v01_replication"
    if not source.is_dir():
        pytest.skip("authoritative closed-pattern evaluation is not available")

    aggregate, inputs = make_paper.validate_closed(source / "aggregate.json")

    original = aggregate["synthetic"]["aligned_indexed"]["original"]
    closed = aggregate["synthetic"]["aligned_indexed"]["closed_exact_extension"]
    assert original["cases"] == closed["cases"] == 500
    assert original["recovered_positive_cases"] == 404
    assert closed["recovered_positive_cases"] == 420
    assert original["false_positive_case_count"] == 0
    assert closed["false_positive_case_count"] == 0
    assert aggregate["real_pilot"]["aligned_indexed"]["files"] == 128
    assert aggregate["real_pilot"]["aligned_indexed"]["changed_file_count"] == 19
    assert "completion_receipt" in inputs


def test_closed_evaluation_rejects_rebound_synthetic_aggregate_tampering(
    tmp_path: Path,
) -> None:
    source = ROOT / "research_local" / "closed_patterns_v01_replication"
    target = _frozen_copy(source, tmp_path, "closed")
    aggregate_path = target / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["synthetic"]["aligned_indexed"]["closed_exact_extension"]["occurrence"]["f1"] = 0.0
    _write(aggregate_path, aggregate)
    _rebind_completed_artifact(target, "aggregate.json")

    with pytest.raises(ValueError, match="differs from raw results"):
        make_paper.validate_closed(aggregate_path)


def test_closed_evaluation_rejects_rebound_real_change_count_tampering(
    tmp_path: Path,
) -> None:
    source = ROOT / "research_local" / "closed_patterns_v01_replication"
    target = _frozen_copy(source, tmp_path, "closed")
    aggregate_path = target / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["real_pilot"]["aligned_indexed"]["changed_file_count"] = 18
    _write(aggregate_path, aggregate)
    _rebind_completed_artifact(target, "aggregate.json")

    with pytest.raises(ValueError, match="differs from raw results"):
        make_paper.validate_closed(aggregate_path)


def test_closed_evaluation_rejects_rebound_paired_interval_tampering(
    tmp_path: Path,
) -> None:
    source = ROOT / "research_local" / "closed_patterns_v01_replication"
    target = _frozen_copy(source, tmp_path, "closed")
    aggregate_path = target / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["paired_deltas"]["aligned_indexed"]["occurrence_f1"][
        "case_bootstrap_ci95"
    ][1] = 0.5
    _write(aggregate_path, aggregate)
    _rebind_completed_artifact(target, "aggregate.json")

    with pytest.raises(ValueError, match="differs from raw results"):
        make_paper.validate_closed(aggregate_path)


def test_metamorphic_evaluation_checks_frozen_coverage_and_counts(tmp_path):
    source = ROOT / "research_local" / "metamorphic_v01"
    target = _frozen_copy(source, tmp_path, "metamorphic")
    result, _ = make_paper.validate_metamorphic(target / "aggregate.json")
    assert result["source_count"] == 128
    assert result["evaluated_rows"] == 1152
    assert result["total_failures"] == 0
    path = target / "aggregate.json"
    result["total_failures"] = 1
    _write(path, result)
    _rebind_completed_artifact(target, "aggregate.json")
    with pytest.raises(ValueError, match="failure count"):
        make_paper.validate_metamorphic(path)


def test_metamorphic_evaluation_rejects_duplicated_cohort_row(tmp_path):
    source = ROOT / "research_local" / "metamorphic_v01"
    target = _frozen_copy(source, tmp_path, "metamorphic")
    path = target / "raw_results.json"
    raw = json.loads(path.read_text())
    raw["rows"][-1] = raw["rows"][0]
    _write(path, raw)
    _rebind_completed_artifact(target, "raw_results.json")
    with pytest.raises(ValueError, match="row coverage"):
        make_paper.validate_metamorphic(target / "aggregate.json")


def test_part_ranking_recomputes_heldout_role_agreement_and_bootstrap() -> None:
    study = ROOT / "research_local" / "part_ranking_v01"
    audit = ROOT / "research_local" / "part_ranking_audit_v01"
    if not study.is_dir() or not audit.is_dir():
        pytest.skip("part ranking evidence is not available")

    result, inputs = make_paper.validate_part_ranking(study, audit)

    assert result["selected_preset"] == "monophony"
    assert result["development"]["songs"] == 60
    assert result["heldout"]["songs"] == 120
    assert result["heldout"]["baseline_top1"] == 76
    assert result["heldout"]["prior_top1"] == 110
    assert result["heldout"]["baseline_top3"] == 102
    assert result["heldout"]["prior_top3"] == 119
    assert result["heldout"]["paired_top1_difference"]["ci95"] == [0.20833333, 0.36666667]
    assert result["curation_truncated"]["heldout"] == 120
    assert "audit_completion_receipt" in inputs


def test_part_ranking_rejects_rebound_missing_raw_row(tmp_path: Path) -> None:
    source = ROOT / "research_local" / "part_ranking_v01"
    audit = ROOT / "research_local" / "part_ranking_audit_v01"
    target = _frozen_copy(source, tmp_path, "part-ranking")
    raw_path = target / "raw_results.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["rows"].pop()
    _write(raw_path, raw)
    _rebind_completed_artifact(target, "raw_results.json")

    with pytest.raises(ValueError, match="raw row coverage"):
        make_paper.validate_part_ranking(target, audit)


def test_part_ranking_rejects_rebound_aggregate_count(tmp_path: Path) -> None:
    source = ROOT / "research_local" / "part_ranking_v01"
    audit = ROOT / "research_local" / "part_ranking_audit_v01"
    target = _frozen_copy(source, tmp_path, "part-ranking-count")
    aggregate_path = target / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["heldout"]["part_prior"]["top1_melody_count"] = 109
    _write(aggregate_path, aggregate)
    _rebind_completed_artifact(target, "aggregate.json")

    with pytest.raises(ValueError, match="aggregate count mismatch"):
        make_paper.validate_part_ranking(target, audit)


def test_part_ranking_rejects_independent_audit_receipt_tampering(
    tmp_path: Path,
) -> None:
    study = ROOT / "research_local" / "part_ranking_v01"
    source_audit = ROOT / "research_local" / "part_ranking_audit_v01"
    audit = _frozen_copy(source_audit, tmp_path, "part-ranking-audit")
    results_path = audit / "audit_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results["metrics"]["heldout"]["prior_top1"] = 120
    _write(results_path, results)

    with pytest.raises(ValueError, match="result hash mismatch"):
        make_paper.validate_part_ranking(study, audit)


def test_certified_drums_recomputes_coverage_and_wilson() -> None:
    study = ROOT / "research_local" / "certified_drums_v01"
    audit = ROOT / "research_local" / "certified_drums_audit_v01"
    if not study.is_dir() or not audit.is_dir():
        pytest.skip("certified drum evidence is not available")

    result, inputs = make_paper.validate_certified_drums(study, audit)

    tolerant = result["methods"]["tolerant"]["test"]
    assert tolerant["negative_cases_with_output"] == 0
    assert tolerant["negative_cases"] == 120
    assert tolerant["negative_output_wilson_95"][1] == pytest.approx(0.0310191664)
    assert tolerant["positive_target_pairs_covered_by_direct_detector_edges"] == 120
    assert tolerant["positive_target_pairs"] == 180
    assert result["family_recovery_posthoc"]["tolerant"]["test"] == {
        "families_covering_all_labelled_target_windows": 60,
        "family_recovery_rate": 1.0,
        "positive_cases": 60,
    }
    assert "audit_input_manifest" in inputs


def test_certified_drums_rejects_rebound_method_coverage_tampering(
    tmp_path: Path,
) -> None:
    source = ROOT / "research_local" / "certified_drums_v01"
    audit = ROOT / "research_local" / "certified_drums_audit_v01"
    target = _frozen_copy(source, tmp_path, "certified-drums")
    raw_path = target / "raw_results.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["methods"]["tolerant"].pop()
    _write(raw_path, raw)
    _rebind_completed_artifact(target, "raw_results.json")

    with pytest.raises(ValueError, match="method coverage mismatch"):
        make_paper.validate_certified_drums(target, audit)


def test_certified_drums_rejects_rebound_aggregate_count(tmp_path: Path) -> None:
    source = ROOT / "research_local" / "certified_drums_v01"
    audit = ROOT / "research_local" / "certified_drums_audit_v01"
    target = _frozen_copy(source, tmp_path, "certified-drum-count")
    aggregate_path = target / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["methods"]["tolerant"]["by_split"]["test"][
        "negative_cases_with_output"
    ] = 1
    _write(aggregate_path, aggregate)
    _rebind_completed_artifact(target, "aggregate.json")

    with pytest.raises(ValueError, match="differs from raw results"):
        make_paper.validate_certified_drums(target, audit)


def test_certified_drums_rejects_audit_source_binding_tampering(
    tmp_path: Path,
) -> None:
    study = ROOT / "research_local" / "certified_drums_v01"
    source_audit = ROOT / "research_local" / "certified_drums_audit_v01"
    audit = _frozen_copy(source_audit, tmp_path, "certified-drum-audit")
    report_path = audit / "audit.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["study_completion_receipt_sha256"] = "0" * 64
    _write(report_path, report)

    with pytest.raises(ValueError, match="audit artifact changed"):
        make_paper.validate_certified_drums(study, audit)


def _selection_inputs() -> tuple[Path, Path, Path]:
    return (
        ROOT / "research_local" / "selection_external_v01" / "aggregate.json",
        ROOT / "research_local" / "external" / "theme_transformer",
        ROOT / "research_local" / "theme_annotation_input_audit.json",
    )


def test_external_selection_recomputes_theme_and_jku_metrics() -> None:
    aggregate, theme_root, theme_audit = _selection_inputs()
    if not aggregate.is_file():
        pytest.skip("external selector evidence is not available")

    result, inputs = make_paper.validate_selection_external(
        aggregate, theme_root, theme_audit,
    )

    assert result["run_count"] == 48
    assert result["all_runs_truncated"] is True
    assert result["theme"]["changes"] == {
        "aligned_closed": 1, "aligned_melody": 1,
    }
    assert result["jku"]["changes"] == {
        "aligned_closed": 0, "aligned_melody": 3,
    }
    indexed = result["jku"]["groups"]["polyphonic/aligned_indexed"]["macro_metrics"]
    melody = result["jku"]["groups"]["polyphonic/aligned_melody"]["macro_metrics"]
    assert indexed["F_est"] == pytest.approx(0.2392285097)
    assert melody["F_est"] == pytest.approx(0.2372137943)
    assert melody["F_occ.75"] == indexed["F_occ.75"]
    assert "prior_theme_completion_receipt.json" in inputs
    assert "prior_jku_raw_results.json" in inputs


def test_external_selection_rejects_missing_method_row(tmp_path: Path) -> None:
    aggregate, theme_root, theme_audit = _selection_inputs()
    target = _frozen_copy(aggregate.parent, tmp_path, "selector")
    raw_path = target / "raw_results.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["theme_runs"].pop()
    _write(raw_path, raw)
    _rebind_completed_artifact(target, "raw_results.json")

    with pytest.raises(ValueError, match="Theme method coverage"):
        make_paper.validate_selection_external(
            target / "aggregate.json", theme_root, theme_audit,
        )


def test_external_selection_requires_completion_receipt(tmp_path: Path) -> None:
    aggregate, theme_root, theme_audit = _selection_inputs()
    target = _frozen_copy(aggregate.parent, tmp_path, "selector-unfinished")
    (target / "completion_receipt.json").unlink()
    with pytest.raises(ValueError, match="completed experiment"):
        make_paper.validate_selection_external(
            target / "aggregate.json", theme_root, theme_audit,
        )


def test_external_selection_checks_frozen_source_cohort(monkeypatch) -> None:
    aggregate, theme_root, theme_audit = _selection_inputs()
    if not aggregate.is_file():
        pytest.skip("external selector evidence is not available")
    original = make_paper._load_pair

    def altered(*args, **kwargs):
        result, raw, receipt, inputs = original(*args, **kwargs)
        receipt["case_cohort"][-1]["source_subset_sha256"] = "0" * 64
        return result, raw, receipt, inputs

    monkeypatch.setattr(make_paper, "_load_pair", altered)
    with pytest.raises(ValueError, match="selection.frozen_cohort"):
        make_paper.validate_selection_external(aggregate, theme_root, theme_audit)


def test_external_selection_rejects_rebound_prediction_tampering(tmp_path: Path) -> None:
    aggregate, theme_root, theme_audit = _selection_inputs()
    target = _frozen_copy(aggregate.parent, tmp_path, "selector-prediction")
    raw_path = target / "raw_results.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["theme_runs"][0]["predicted_source_note_indices"]["top1"] = []
    _write(raw_path, raw)
    _rebind_completed_artifact(target, "raw_results.json")

    with pytest.raises(ValueError, match="predictions"):
        make_paper.validate_selection_external(
            target / "aggregate.json", theme_root, theme_audit,
        )


def test_external_selection_rejects_rebound_jku_metric_tampering(tmp_path: Path) -> None:
    aggregate, theme_root, theme_audit = _selection_inputs()
    target = _frozen_copy(aggregate.parent, tmp_path, "selector-jku")
    raw_path = target / "raw_results.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["jku_runs"][0]["metrics"]["F_est"] = 1.0
    _write(raw_path, raw)
    _rebind_completed_artifact(target, "raw_results.json")

    with pytest.raises(ValueError, match=r"metrics\.F_est differs"):
        make_paper.validate_selection_external(
            target / "aggregate.json", theme_root, theme_audit,
        )


def test_external_selection_rejects_rebound_golden_tampering(tmp_path: Path) -> None:
    aggregate, theme_root, theme_audit = _selection_inputs()
    target = _frozen_copy(aggregate.parent, tmp_path, "selector-golden")
    raw_path = target / "raw_results.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["jku_published_metric_examples"]["examples"]["algo1"]["scores"]["F"] = 123.456
    _write(raw_path, raw)
    _rebind_completed_artifact(target, "raw_results.json")

    with pytest.raises(ValueError, match="published golden"):
        make_paper.validate_selection_external(
            target / "aggregate.json", theme_root, theme_audit,
        )


def test_external_selection_rejects_rebound_prior_regression_tampering(
    tmp_path: Path,
) -> None:
    aggregate, theme_root, theme_audit = _selection_inputs()
    target = _frozen_copy(aggregate.parent, tmp_path, "selector-prior")
    for filename in ("raw_results.json", "aggregate.json"):
        path = target / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["prior_indexed_regression"]["theme"]["passed"] = False
        _write(path, payload)
        _rebind_completed_artifact(target, filename)

    with pytest.raises(ValueError, match="prior regression did not pass"):
        make_paper.validate_selection_external(
            target / "aggregate.json", theme_root, theme_audit,
        )
