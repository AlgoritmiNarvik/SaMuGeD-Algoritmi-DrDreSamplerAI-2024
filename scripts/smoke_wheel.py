"""Build a committed wheel and test installation outside the Git checkout."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile


FIXTURE_SCRIPT = r'''
import importlib.metadata as md
import json
from pathlib import Path
import sys
from hashlib import sha256
import mido
import samuged
from samuged.evaluate import generate_cases, _write_case

source = Path("inputs")
source.mkdir()
for case in generate_cases(20)[:6]:
    _write_case(case, source / f"{case.case_id}.mid")
midi = mido.MidiFile(ticks_per_beat=480)
track = mido.MidiTrack()
midi.tracks.append(track)
track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
events = []
for bar in range(8):
    for step in range(8):
        tick = bar * 1920 + step * 240
        pitches = [42, 36] if step % 4 == 0 else [42, 38] if step % 4 == 2 else [42]
        for pitch in pitches:
            events.extend([(tick, 1, pitch, 96), (tick + 60, 0, pitch, 0)])
last = 0
for tick, on, pitch, velocity in sorted(events):
    track.append(mido.Message("note_on" if on else "note_off", channel=9,
                              note=pitch, velocity=velocity, time=tick-last))
    last = tick
midi.save(source / "drums.mid")
melody_path = next(path for path in sorted(source.glob("*.mid")) if path.name != "drums.mid")
damaged = mido.MidiFile(melody_path)
damaged.tracks[0].insert(0, mido.MetaMessage("key_signature", key="C", time=0))
damaged.save(source / "invalid-key.mid")
path = source / "invalid-key.mid"
payload = path.read_bytes()
assert b"\xff\x59\x02\x00\x00" in payload
path.write_bytes(payload.replace(b"\xff\x59\x02\x00\x00", b"\xff\x59\x02\x7f\x7f", 1))
print(json.dumps({"module_path": samuged.__file__, "python": sys.version,
                  "distributions": {item.metadata["Name"]: item.version for item in md.distributions()},
                  "installed_source_sha256": {"samuged/" + path.name: sha256(path.read_bytes()).hexdigest()
                                              for path in Path(samuged.__file__).parent.glob("*.py")},
                  "fixture_count": len(list(source.glob("*.mid")))}))
'''


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def run(output: Path, *, revision: str = "HEAD", algorithms: tuple[str, ...] = (
    "reference", "aligned_closed"
)) -> dict:
    repository = Path(__file__).resolve().parents[1]
    output = output.resolve()
    if output.exists():
        raise ValueError("wheel smoke output must be new")
    if not algorithms or any(name not in {
        "reference", "aligned", "aligned_indexed", "aligned_closed", "aligned_melody"
    } for name in algorithms) or len(set(algorithms)) != len(algorithms):
        raise ValueError("algorithms must be distinct supported names")
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
        cwd=repository, text=True, stderr=subprocess.PIPE, timeout=60,
    ).strip()
    output.mkdir(parents=True)
    driver = Path(__file__).resolve().read_bytes()
    (output / "smoke_driver.py").write_bytes(driver)
    source = output / "source"
    source.mkdir()
    names = subprocess.check_output(
        ["git", "ls-tree", "-rz", "--name-only", commit, "samuged", "pyproject.toml",
         "LICENSE", "requirements-research.lock"], cwd=repository, timeout=60,
    ).decode().split("\0")
    inventory = []
    for name in filter(None, names):
        target = source / name
        if not target.resolve().is_relative_to(source):
            raise ValueError("source archive path escapes snapshot")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=repository, timeout=60))
        inventory.append({"path": name, "sha256": _sha(target)})
    (output / "source_receipt.json").write_text(json.dumps(
        {"source_git_commit": commit, "driver_sha256": sha256(driver).hexdigest(),
         "files": inventory}, indent=2
    ) + "\n")
    (output / "fixtures.py").write_text(FIXTURE_SCRIPT)
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(key, None)
    environment["UV_LINK_MODE"] = "copy"
    commands = []

    def execute(command: list[str], cwd: Path, label: str) -> str:
        started = time.monotonic()
        result = subprocess.run(command, cwd=cwd, env=environment, text=True,
                                capture_output=True, timeout=60)
        (output / f"{label}.stdout.txt").write_text(result.stdout)
        (output / f"{label}.stderr.txt").write_text(result.stderr)
        commands.append({"label": label, "command": command, "cwd": str(cwd),
                         "returncode": result.returncode,
                         "elapsed_seconds": round(time.monotonic()-started, 6)})
        if result.returncode:
            raise RuntimeError(f"{label} failed; see {output / (label + '.stderr.txt')}")
        return result.stdout

    try:
        uv_version = execute(["uv", "--version"], repository, "uv_version").strip()
        execute(["uv", "build", "--wheel", "--offline", "--out-dir", str(output / "dist"),
                 str(source)], repository, "build_wheel")
        wheels = list((output / "dist").glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("expected exactly one wheel")
        wheel = wheels[0]
        with zipfile.ZipFile(wheel) as archive:
            wheel_metadata = {name: archive.read(name).decode() for name in archive.namelist()
                              if name.endswith((".dist-info/WHEEL", ".dist-info/METADATA"))}
        expected_code = {row["path"]: row["sha256"] for row in inventory
                         if row["path"].startswith("samuged/") and row["path"].endswith(".py")}
        expected_version = tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"]
        results = {}
        with tempfile.TemporaryDirectory(prefix="samuged-wheel-test-") as temporary:
            isolated = Path(temporary).resolve()
            if isolated.is_relative_to(repository):
                raise ValueError("installation test must run outside the checkout")
            venv = isolated / "venv"
            python = venv / "bin" / "python"
            execute(["uv", "venv", "--python", sys.executable, str(venv)], isolated, "create_venv")
            execute(["uv", "pip", "install", "--python", str(python), "--offline", str(wheel)],
                    isolated, "install_wheel")
            installation = json.loads(execute([str(python), "-I", "-c", FIXTURE_SCRIPT],
                                              isolated, "fixtures"))
            if not Path(installation["module_path"]).resolve().is_relative_to(venv):
                raise ValueError("samuged imported outside the isolated wheel installation")
            if installation["installed_source_sha256"] != expected_code:
                raise ValueError("installed Python source differs from committed source")
            if installation["distributions"].get("samuged-phrases") != expected_version:
                raise ValueError("installed distribution version differs from committed metadata")
            if installation["fixture_count"] != 8:
                raise ValueError("fixture generation did not create the eight intended inputs")
            source_hashes = {path.name: _sha(path) for path in (isolated / "inputs").glob("*.mid")}
            if not {"drums.mid", "invalid-key.mid"} <= set(source_hashes):
                raise ValueError("required percussion or metadata recovery fixture is absent")
            for algorithm in algorithms:
                execute([str(venv / "bin" / "samuged"), "build", "--source", "inputs", "--output",
                         algorithm, "--workers", "2", "--percussion", "--recover-invalid-keys",
                         "--algorithm", algorithm], isolated, f"build_{algorithm}")
                audit = json.loads(execute([str(python), "-I", "-m", "samuged.audit", "--source",
                    "inputs", "--output", algorithm, "--require-full", "--reextract"],
                    isolated, f"audit_{algorithm}"))
                summary = json.loads((isolated / algorithm / "summary.json").read_text())
                sources = {row["source_path"]: row for line in
                           (isolated / algorithm / "sources.jsonl").read_text().split("\n")
                           if line.strip() and (row := json.loads(line))}
                repaired = {name for name, row in sources.items() if row.get("metadata_repairs")}
                if repaired != {"invalid-key.mid"}:
                    raise ValueError("metadata recovery did not belong to the intended fixture")
                if {phrase["kind"] for phrase in sources["drums.mid"]["phrases"]} != {"percussion"}:
                    raise ValueError("drum fixture did not produce a separate percussion candidate")
                if (audit.get("passed") is not True or audit.get("failure_count") != 0
                        or audit.get("full_source_coverage_required") is not True
                        or audit.get("reextraction_required") is not True
                        or audit.get("source_files") != installation["fixture_count"]
                        or audit.get("counts", {}).get("sources_verified") != installation["fixture_count"]
                        or audit.get("counts", {}).get("midi_verified") != audit.get("phrase_rows")
                        or summary["source_status"] != {"ok": installation["fixture_count"]}
                        or summary["metadata_recovered_files"] != 1
                        or min(summary["phrase_counts"].get(kind, 0) for kind in ("melodic", "percussion")) < 1):
                    raise ValueError(f"unexpected isolated extraction result: {algorithm}")
                for operation in ("build", "audit"):
                    if "fatal:" in (output / f"{operation}_{algorithm}.stderr.txt").read_text():
                        raise ValueError("successful installed CLI emitted a fatal diagnostic")
                results[algorithm] = {"summary": summary, "audit": audit}
                shutil.copytree(isolated / algorithm, output / "results" / algorithm)
            if source_hashes != {path.name: _sha(path) for path in (isolated / "inputs").glob("*.mid")}:
                raise ValueError("source fixtures changed during build")
            shutil.copytree(isolated / "inputs", output / "inputs")
        report = {"schema_version": "samuged-wheel-smoke-v1", "passed": True,
                  "source_git_commit": commit, "wheel": wheel.name, "wheel_sha256": _sha(wheel),
                  "driver_sha256": sha256(driver).hexdigest(),
                  "uv_version": uv_version, "wheel_metadata": wheel_metadata,
                  "installation": installation, "source_sha256": source_hashes, "results": results,
                  "claim_boundary": "local wheel installation and synthetic CLI smoke, not corpus quality"}
        (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    finally:
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    artifacts = {path.relative_to(output).as_posix(): _sha(path)
                 for path in sorted(output.rglob("*")) if path.is_file()}
    (output / "completion.json").write_text(json.dumps({
        "schema_version": "samuged-wheel-smoke-completion-v1", "status": "completed",
        "source_git_commit": commit, "artifacts": artifacts,
    }, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--algorithms", nargs="+", default=["reference", "aligned_closed"])
    args = parser.parse_args()
    result = run(args.output, revision=args.revision, algorithms=tuple(args.algorithms))
    print(json.dumps({"passed": result["passed"], "commit": result["source_git_commit"],
                      "algorithms": list(result["results"]), "output": str(args.output)}, indent=2))
