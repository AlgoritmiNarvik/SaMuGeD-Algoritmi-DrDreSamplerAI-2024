"""Upload prepared dataset and static Space folders to the authenticated account.

The command defaults to an inventory preview. Pass --publish to write to the Hub.
With --dataset-only the prepared folder is added to the existing dataset repository:
files present in the folder are added or replaced and no other repository file is deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def public_files(folder: Path, *, dataset: bool, require_readme: bool = True) -> list[str]:
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
    if require_readme and "README.md" not in files:
        raise ValueError("prepared publication requires a README")
    if not files:
        raise ValueError("prepared publication folder has no files")
    return files


def file_sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def repo_path(prefix: str, path: str) -> str:
    return (PurePosixPath(prefix) / path).as_posix() if prefix else path


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--space", type=Path)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--dataset-name", default="samuged-recurring-phrases")
    parser.add_argument("--space-name", default="samuged-earworms")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--dataset-only", action="store_true",
                        help="add or replace only the files in --dataset inside the existing dataset repository")
    parser.add_argument("--path-in-repo", default="",
                        help="repository folder for --dataset-only uploads, the repository root by default")
    parser.add_argument("--commit-message", default=None)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    if args.dataset_only and args.space is not None:
        parser.error("--dataset-only does not take --space")
    if args.path_in_repo and not args.dataset_only:
        parser.error("--path-in-repo requires --dataset-only")
    prefix = PurePosixPath(args.path_in_repo) if args.path_in_repo else None
    if prefix is not None and (prefix.is_absolute() or ".." in prefix.parts):
        parser.error("--path-in-repo must be a relative repository folder")
    args.path_in_repo = prefix.as_posix() if prefix is not None else ""
    return args


def run(args: argparse.Namespace, api) -> dict:
    if api.whoami()["name"] != args.owner:
        raise ValueError("authenticated account differs from publication owner")
    targets = [("dataset", args.dataset_name, args.dataset)]
    if args.space is not None:
        targets.append(("space", args.space_name, args.space))
    prepared = [(kind, f"{args.owner}/{name}", folder,
                 public_files(folder, dataset=kind == "dataset", require_readme=not args.dataset_only))
                for kind, name, folder in targets]
    if not args.publish:
        preview = {kind: {"repo": repo, "files": len(files), "bytes": sum((folder / p).stat().st_size for p in files),
                          "mode": "add_or_replace_only" if args.dataset_only else "release",
                          "path_in_repo": args.path_in_repo or "."}
                   for kind, repo, folder, files in prepared}
        print(json.dumps(preview, indent=2))
        return preview
    receipt = {}
    for kind, repo, folder, files in prepared:
        if args.dataset_only:
            # The dataset already exists; never create it here and never pass delete patterns.
            message = args.commit_message or "Add corpus expansion configurations"
            commit = api.upload_folder(repo_id=repo, repo_type=kind, folder_path=folder, allow_patterns=files,
                                       path_in_repo=args.path_in_repo or None, commit_message=message)
        else:
            api.create_repo(repo, repo_type=kind, private=False, exist_ok=True,
                            **({"space_sdk": "static"} if kind == "space" else {}))
            commit = api.upload_folder(repo_id=repo, repo_type=kind, folder_path=folder, allow_patterns=files,
                                       commit_message=args.commit_message or "Publish recurring phrase research release")
        receipt[kind] = {"repo_id": repo, "commit": commit.oid, "url": commit.repo_url,
                         "mode": "add_or_replace_only" if args.dataset_only else "release",
                         "path_in_repo": args.path_in_repo or ".",
                         "files": {repo_path(args.path_in_repo, p): {"bytes": (folder / p).stat().st_size,
                                                                    "sha256": file_sha256(folder / p)} for p in files}}
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(kind, repo, commit.oid, "uploaded", len(files), "files", flush=True)
    return receipt


def main(argv=None) -> None:
    args = parse_args(argv)
    from huggingface_hub import HfApi
    run(args, HfApi())


if __name__ == "__main__":
    main()
