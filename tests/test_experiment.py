import json
from hashlib import sha256

import pytest

import samuged.evaluate as evaluate
import samuged.experiment as experiment
from samuged.evaluate import generate_cases, run_benchmark
from samuged.experiment import (
    sha256_json, prepare_experiment, receipt_links, complete_experiment,
    verify_completed_experiment, verify_start_receipt,
)


def test_snapshot_follows_transitive_imports_and_package_initializers(tmp_path, monkeypatch):
    project = tmp_path / "project"
    sources = {
        "pkg/__init__.py": "from . import initialization\n",
        "pkg/initialization.py": "import pathlib\n",
        "pkg/sub/__init__.py": "",
        "pkg/sub/entry.py": "from ..core import value\nfrom . import sibling\n",
        "pkg/sub/sibling.py": "from pkg import extra\n",
        "pkg/core.py": "from .sub import entry\nvalue = 1\n",
        "pkg/extra.py": "raise RuntimeError('must not execute imports')\n",
        "unused.py": "raise RuntimeError('unrelated')\n",
    }
    for name, code in sources.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code)
    monkeypatch.setattr(experiment, "_REPOSITORY_ROOT", project)
    selected = experiment._relative_source_files(["pkg/sub/entry.py"])
    assert {path.relative_to(project).as_posix() for path in selected} == set(sources) - {"unused.py"}


def test_snapshot_includes_conditional_and_namespace_imports(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "main.py").write_text(
        "if False:\n    from scripts import optional\nimport scripts.helper\n"
    )
    (tmp_path / "scripts" / "optional.py").write_text("import json\n")
    (tmp_path / "scripts" / "helper.py").write_text("")
    monkeypatch.setattr(experiment, "_REPOSITORY_ROOT", tmp_path)
    selected = experiment._relative_source_files(["scripts/main.py"])
    assert {path.name for path in selected} == {"main.py", "optional.py", "helper.py"}


def test_snapshot_rejects_imported_symlink_escape(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.py").write_text("value = 3\n")
    (project / "entry.py").write_text("import escaped\n")
    (project / "escaped.py").symlink_to(tmp_path / "outside.py")
    monkeypatch.setattr(experiment, "_REPOSITORY_ROOT", project)
    with pytest.raises(ValueError, match="import escapes repository"):
        experiment._relative_source_files(["entry.py"])


def test_snapshot_reaches_real_midi_dependencies_from_single_entrypoint():
    selected = experiment._relative_source_files(["samuged/midi.py"])
    names = {path.relative_to(experiment._REPOSITORY_ROOT).as_posix() for path in selected}
    assert {"samuged/__init__.py", "samuged/midi.py", "samuged/metadata_recovery.py"} <= names


def test_receipt_is_written_before_first_detector_result(tmp_path, monkeypatch):
    output = tmp_path / "evaluation"
    observed = {}
    original_extract = evaluate.extract

    def wrapped_extract(song, config):
        observed["receipt"] = json.loads((output / "experiment_receipt.json").read_text())
        observed["raw_exists"] = (output / "raw_results.json").exists()
        return original_extract(song, config)

    monkeypatch.setattr(evaluate, "extract", wrapped_extract)
    run_benchmark(output, seeds=1, legacy_limit=0, bootstrap_iterations=1)

    assert observed["receipt"]["status"] == "started"
    assert observed["raw_exists"] is False
    assert observed["receipt"]["case_cohort_sha256"] == sha256_json(
        observed["receipt"]["case_cohort"]
    )


def test_nonempty_output_is_rejected_before_overwrite(tmp_path):
    output = tmp_path / "evaluation"
    run_benchmark(output, seeds=1, legacy_limit=0, bootstrap_iterations=1)
    before = (output / "experiment_receipt.json").read_bytes()

    with pytest.raises(FileExistsError):
        run_benchmark(output, seeds=1, legacy_limit=0, bootstrap_iterations=1)

    assert (output / "experiment_receipt.json").read_bytes() == before


def test_snapshot_and_receipt_hash_links_are_reproducible(tmp_path):
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    first = run_benchmark(first_output, seeds=2, legacy_limit=0, bootstrap_iterations=1)
    second = run_benchmark(second_output, seeds=2, legacy_limit=0, bootstrap_iterations=1)
    first_receipt = json.loads((first_output / "experiment_receipt.json").read_text())
    snapshot = json.loads((first_output / "source_snapshot.json").read_text())
    first_raw = json.loads((first_output / "raw_results.json").read_text())

    assert snapshot["snapshot_sha256"] == sha256_json(
        {"version": snapshot["snapshot_version"], "files": snapshot["files"]}
    )
    for entry in snapshot["files"]:
        path = first_output / "source_snapshot" / entry["path"]
        assert sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    assert sha256((first_output / "experiment_receipt.json").read_bytes()).hexdigest() == first["receipt_sha256"]
    assert first["receipt_sha256"] == first_raw["receipt_sha256"]
    assert first["source_snapshot_sha256"] == first_raw["source_snapshot_sha256"]
    assert first["case_cohort_sha256"] == first_raw["case_cohort_sha256"]
    assert first["source_snapshot_sha256"] == second["source_snapshot_sha256"]
    assert first["case_cohort_sha256"] == second["case_cohort_sha256"]
    assert first_receipt["runtime"]["python"]
    assert "mido" in first_receipt["runtime"]["packages"]


def test_receipt_cohort_matches_reproducible_synthetic_cases(tmp_path):
    output = tmp_path / "evaluation"
    run_benchmark(output, seeds=4, legacy_limit=0, bootstrap_iterations=1)
    receipt = json.loads((output / "experiment_receipt.json").read_text())
    expected = json.loads(json.dumps([case.metadata() for case in generate_cases(4)]))

    assert receipt["case_cohort"] == expected
    raw = json.loads((output / "raw_results.json").read_text())
    assert [
        {key: value for key, value in case.items() if key not in {"methods", "midi_path", "midi_sha256"}}
        for case in raw["cases"]
    ] == expected


def completed_fixture(output):
    receipt = prepare_experiment(
        output, design={"purpose": "integrity fixture"}, config={"threshold": 1},
        cases=[{"case_id": "first"}], required_files=("samuged/experiment.py",),
    )
    for name in ("raw_results.json", "aggregate.json"):
        (output/name).write_text(json.dumps({**receipt_links(receipt), "value": 42}) + "\n")
    return receipt


def test_completion_binds_results_without_mutating_start_receipt(tmp_path):
    completed_fixture(tmp_path)
    before = (tmp_path/"experiment_receipt.json").read_bytes()
    result = complete_experiment(tmp_path)
    assert result == verify_completed_experiment(tmp_path)
    assert result["status"] == "completed"
    assert result["required_artifacts"] == ["aggregate.json", "raw_results.json"]
    assert (tmp_path/"experiment_receipt.json").read_bytes() == before
    with pytest.raises(FileExistsError):
        complete_experiment(tmp_path, ["aggregate.json"])


def test_completed_results_reject_byte_changes(tmp_path):
    completed_fixture(tmp_path)
    complete_experiment(tmp_path, ["raw_results.json", "aggregate.json"])
    (tmp_path/"raw_results.json").write_text("{}\n")
    with pytest.raises(ValueError, match="completed result changed"):
        verify_completed_experiment(tmp_path)


def test_completion_rejects_wrong_provenance_and_snapshot_changes(tmp_path):
    completed_fixture(tmp_path)
    result_path = tmp_path/"aggregate.json"
    original = result_path.read_text()
    bad = json.loads(original)
    bad["receipt_sha256"] = "0"*64
    result_path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="provenance links mismatch"):
        complete_experiment(tmp_path)
    assert not (tmp_path/"completion_receipt.json").exists()
    result_path.write_text(original)
    (tmp_path/"source_snapshot"/"samuged"/"experiment.py").write_text("changed")
    with pytest.raises(ValueError, match="snapshot file mismatch"):
        complete_experiment(tmp_path)


def test_completion_requires_the_frozen_result_set(tmp_path):
    completed_fixture(tmp_path)
    with pytest.raises(ValueError, match="frozen expected result set"):
        complete_experiment(tmp_path, ["aggregate.json"])
    with pytest.raises(ValueError, match="frozen expected result set"):
        complete_experiment(
            tmp_path, ["aggregate.json", "raw_results.json", "report.json"]
        )
    assert not (tmp_path/"completion_receipt.json").exists()


def test_design_can_freeze_a_custom_result_set(tmp_path):
    receipt = prepare_experiment(
        tmp_path,
        design={"purpose": "custom", "result_artifacts": ["metrics.json"]},
        config={"threshold": 1}, cases=[{"case_id": "first"}],
        required_files=("samuged/experiment.py",),
    )
    (tmp_path/"metrics.json").write_text(
        json.dumps({**receipt_links(receipt), "value": 42}) + "\n"
    )

    completed = complete_experiment(tmp_path)

    assert completed["required_artifacts"] == ["metrics.json"]
    assert verify_completed_experiment(tmp_path) == completed


def test_existing_v1_completion_without_required_field_remains_valid(tmp_path):
    completed_fixture(tmp_path)
    complete_experiment(tmp_path)
    path = tmp_path/"completion_receipt.json"
    legacy = json.loads(path.read_text())
    del legacy["required_artifacts"]
    path.write_text(json.dumps(legacy) + "\n")

    assert verify_completed_experiment(tmp_path)["status"] == "completed"


def test_completion_rejects_artifacts_outside_output(tmp_path):
    output = tmp_path/"outside-experiment"
    outside = tmp_path/"outside.json"
    receipt = prepare_experiment(
        output, design={"result_artifacts": ["../outside.json"]}, config={},
        cases=[], required_files=("samuged/experiment.py",),
    )
    outside.write_text(json.dumps({**receipt_links(receipt), "value": 1}))
    with pytest.raises(ValueError, match="unsafe experiment artifact path"):
        complete_experiment(output)

    linked_output = tmp_path/"linked-experiment"
    linked_receipt = prepare_experiment(
        linked_output, design={"result_artifacts": ["linked.json"]}, config={},
        cases=[], required_files=("samuged/experiment.py",),
    )
    outside.write_text(json.dumps({**receipt_links(linked_receipt), "value": 1}))
    (linked_output/"linked.json").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes output directory"):
        complete_experiment(linked_output)


@pytest.mark.parametrize(
    "name,verify",
    [
        ("experiment_receipt.json", verify_start_receipt),
        ("source_snapshot.json", verify_start_receipt),
        ("completion_receipt.json", verify_completed_experiment),
    ],
)
def test_fixed_receipt_files_must_remain_inside_experiment(tmp_path, name, verify):
    output = tmp_path/"experiment"
    completed_fixture(output)
    complete_experiment(output)
    external = tmp_path/name
    (output/name).replace(external)
    (output/name).symlink_to(external)

    with pytest.raises(ValueError, match="escapes output directory"):
        verify(output)


def test_source_snapshot_directory_must_remain_inside_experiment(tmp_path):
    output = tmp_path/"experiment"
    completed_fixture(output)
    external = tmp_path/"external-source-snapshot"
    (output/"source_snapshot").replace(external)
    (output/"source_snapshot").symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="directory escapes output directory"):
        verify_start_receipt(output)


def test_generated_midi_is_bound_to_completion_receipt(tmp_path):
    run_benchmark(tmp_path, seeds=2, legacy_limit=0, bootstrap_iterations=1)
    completion = verify_completed_experiment(tmp_path)
    assert len(completion["artifacts"]) == 4
    raw = json.loads((tmp_path / "raw_results.json").read_text())
    case = raw["cases"][0]
    midi = tmp_path / case["midi_path"]
    assert sha256(midi.read_bytes()).hexdigest() == case["midi_sha256"]
    midi.write_bytes(midi.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="completed result changed"):
        verify_completed_experiment(tmp_path)


@pytest.mark.parametrize("iterations", [0, -1, True, 1.5])
def test_invalid_bootstrap_count_rejected_before_output(tmp_path, iterations):
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="bootstrap_iterations"):
        run_benchmark(output, seeds=1, legacy_limit=0, bootstrap_iterations=iterations)
    assert not output.exists()
