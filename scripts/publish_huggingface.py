"""Upload prepared dataset and static Space folders to the authenticated account.

The command defaults to an inventory preview. Pass --publish to write to the Hub.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def public_files(folder: Path, *, dataset: bool) -> list[str]:
    files = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise ValueError("publication folders must not contain symlinks")
        if path.is_file():
            relative = path.relative_to(folder)
            if dataset and relative.parts[0] == "metadata":
                continue
            if any(part.startswith(".") for part in relative.parts):
                continue
            files.append(relative.as_posix())
    if "README.md" not in files:
        raise ValueError("prepared publication requires a README")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--space", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--dataset-name", default="samuged-recurring-phrases")
    parser.add_argument("--space-name", default="samuged-earworm-loops")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    from huggingface_hub import HfApi
    api = HfApi()
    if api.whoami()["name"] != args.owner:
        raise ValueError("authenticated account differs from publication owner")
    targets = [("dataset", args.dataset_name, args.dataset), ("space", args.space_name, args.space)]
    prepared = [(kind, f"{args.owner}/{name}", folder, public_files(folder, dataset=kind == "dataset")) for kind, name, folder in targets]
    if not args.publish:
        print(json.dumps({kind: {"repo": repo, "files": len(files), "bytes": sum((folder / p).stat().st_size for p in files)} for kind, repo, folder, files in prepared}, indent=2))
        return
    receipt = {}
    for kind, repo, folder, files in prepared:
        api.create_repo(repo, repo_type=kind, private=False, exist_ok=True, **({"space_sdk": "static"} if kind == "space" else {}))
        commit = api.upload_folder(repo_id=repo, repo_type=kind, folder_path=folder, allow_patterns=files,
                                   commit_message="Publish recurring phrase research release")
        receipt[kind] = {"repo_id": repo, "commit": commit.oid, "url": commit.repo_url,
                         "files": {p: {"bytes": (folder / p).stat().st_size, "sha256": hashlib.sha256((folder / p).read_bytes()).hexdigest()} for p in files}}
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(kind, repo, commit.oid, "uploaded", len(files), "files", flush=True)


if __name__ == "__main__":
    main()
