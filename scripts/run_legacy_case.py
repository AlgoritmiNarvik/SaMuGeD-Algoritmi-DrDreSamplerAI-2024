"""Run the unchanged legacy detector for one local benchmark case."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.input.resolve(strict=True)
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=True)

    repository = Path(__file__).resolve().parents[1]
    legacy_path = repository / "testing_tools/test_scripts/asle_scripts/pattern_detection_old.py"
    spec = importlib.util.spec_from_file_location("samuged_legacy_detector", legacy_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load legacy detector from {legacy_path}")
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    # Match the dataset builder's default grouped-track configuration. Each
    # legacy pattern remains a separate instrument in the generated MIDI.
    legacy.asle(str(source), str(destination), False)


if __name__ == "__main__":
    main()
