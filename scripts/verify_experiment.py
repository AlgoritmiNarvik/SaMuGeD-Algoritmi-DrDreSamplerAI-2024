"""Verify frozen experiment sources and bind or verify completed result bytes."""
import argparse
import json
from pathlib import Path

from samuged.experiment import complete_experiment, verify_completed_experiment


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--complete", action="store_true",
                        help="bind the frozen expected result set after result review")
    parser.add_argument("--artifact", action="append",
                        help=("result JSON relative to the experiment; when supplied, the complete "
                              "set must equal design.result_artifacts or the default raw_results.json "
                              "and aggregate.json pair"))
    args = parser.parse_args()
    if args.complete:
        result = complete_experiment(args.experiment, args.artifact)
    else:
        if args.artifact:
            parser.error("--artifact requires --complete")
        result = verify_completed_experiment(args.experiment)
    print(json.dumps(result, indent=2, sort_keys=True))
