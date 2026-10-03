"""Validate local JSONL manifests against the dataset schemas."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
DEFAULT_MAX_ERRORS = 20
HARD_MAX_ERRORS = 100
MAX_ERROR_TEXT = 240


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"schema must be a JSON object: {path}")
    Draft202012Validator.check_schema(value)
    return value


def _error_text(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path)
    message = error.message
    if location:
        message = f"{location}: {message}"
    return message[:MAX_ERROR_TEXT]


def validate_manifest(
    path: Path,
    schema_path: Path,
    *,
    max_errors: int = DEFAULT_MAX_ERRORS,
) -> dict[str, Any]:
    """Validate every JSONL row and return bounded diagnostics.

    ``invalid`` counts rows rather than individual schema errors. The complete
    row count is still consumed after the diagnostic limit is reached, so the
    caller can use the result as an exit decision without unbounded output.
    """
    max_errors = max(0, min(max_errors, HARD_MAX_ERRORS))
    validator = Draft202012Validator(_load_json(schema_path))
    result: dict[str, Any] = {
        "path": str(path),
        "rows": 0,
        "valid": 0,
        "invalid": 0,
        "errors": [],
    }
    if not path.is_file():
        result["errors"].append(f"manifest does not exist: {path}")
        result["invalid"] = 1
        return result

    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            result["rows"] += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                result["invalid"] += 1
                if len(result["errors"]) < max_errors:
                    result["errors"].append(
                        f"line {line_number}: invalid JSON: {exc.msg}"[:MAX_ERROR_TEXT]
                    )
                continue

            errors = sorted(
                validator.iter_errors(row),
                key=lambda error: (
                    tuple(str(part) for part in error.absolute_path),
                    str(error.validator),
                ),
            )
            if errors:
                result["invalid"] += 1
                if len(result["errors"]) < max_errors:
                    result["errors"].append(
                        f"line {line_number}: {_error_text(errors[0])}"[:MAX_ERROR_TEXT]
                    )
            else:
                result["valid"] += 1
    return result


def validate_dataset(
    dataset: Path,
    *,
    sources: Path | None = None,
    phrases: Path | None = None,
    max_errors: int = DEFAULT_MAX_ERRORS,
) -> dict[str, Any]:
    """Validate the selected manifests in a local dataset directory."""
    source_path = sources or dataset / "sources.jsonl"
    phrase_path = phrases or dataset / "phrases.jsonl"
    results = {
        "sources": validate_manifest(
            source_path, SCHEMA_DIR / "source.schema.json", max_errors=max_errors
        ),
        "phrases": validate_manifest(
            phrase_path, SCHEMA_DIR / "phrase.schema.json", max_errors=max_errors
        ),
    }
    errors = [
        error
        for result in results.values()
        for error in result["errors"]
    ]
    return {
        "dataset": str(dataset),
        "source_rows": results["sources"]["rows"],
        "phrase_rows": results["phrases"]["rows"],
        "valid_rows": results["sources"]["valid"] + results["phrases"]["valid"],
        "invalid_rows": results["sources"]["invalid"] + results["phrases"]["invalid"],
        "errors": errors[: max(0, min(max_errors, HARD_MAX_ERRORS))],
        "manifests": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_positional",
        nargs="?",
        type=Path,
        help="dataset directory containing sources.jsonl and phrases.jsonl",
    )
    parser.add_argument(
        "--dataset",
        dest="dataset_option",
        type=Path,
        help="dataset directory containing sources.jsonl and phrases.jsonl",
    )
    parser.add_argument("--sources", type=Path, help="validate this source manifest")
    parser.add_argument("--phrases", type=Path, help="validate this phrase manifest")
    parser.add_argument(
        "--max-errors",
        type=int,
        default=DEFAULT_MAX_ERRORS,
        help=f"maximum diagnostics to print (capped at {HARD_MAX_ERRORS})",
    )
    args = parser.parse_args(argv)
    dataset = args.dataset_option or args.dataset_positional
    if dataset is None:
        parser.error("a dataset directory is required (use DATASET or --dataset DATASET)")
    if args.sources is None and args.phrases is None:
        result = validate_dataset(dataset, max_errors=args.max_errors)
    else:
        result = validate_dataset(
            dataset,
            sources=args.sources,
            phrases=args.phrases,
            max_errors=args.max_errors,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["invalid_rows"] else 0


if __name__ == "__main__":
    sys.exit(main())
