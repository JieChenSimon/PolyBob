#!/usr/bin/env python3
"""Prepare and verify the ignored local Kronos runtime.

This script never modifies the reference checkout.  It copies the three model
implementation files into PolyBob's ignored model cache and fixes one absolute
intra-package import so the runtime can be loaded under an isolated module name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from libs.forecasting.kronos import (
    KronosLab,
    KronosLabConfig,
    MODEL_ID,
    MODEL_REVISION,
    SOURCE_REVISION,
    TOKENIZER_ID,
    TOKENIZER_REVISION,
)


def prepare(source: Path, target_root: Path) -> None:
    source_model = source / "model"
    if not (source_model / "kronos.py").is_file():
        raise SystemExit(f"not a Kronos checkout: {source}")
    try:
        revision = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot verify Kronos source revision: {exc}") from exc
    if revision != SOURCE_REVISION:
        raise SystemExit(f"Kronos source is {revision}; expected pinned {SOURCE_REVISION}")
    runtime_model = target_root / "runtime" / "model"
    runtime_model.mkdir(parents=True, exist_ok=True)
    runtime_hashes = {}
    for name in ("__init__.py", "module.py", "kronos.py"):
        text = (source_model / name).read_text()
        if name == "kronos.py":
            text = text.replace("from model.module import *", "from .module import *")
        (runtime_model / name).write_text(text)
        runtime_hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = {
        "source_revision": SOURCE_REVISION,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "tokenizer_id": TOKENIZER_ID,
        "tokenizer_revision": TOKENIZER_REVISION,
        "runtime_sha256": runtime_hashes,
    }
    (target_root / "runtime" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )


def pull(target_root: Path) -> None:
    from huggingface_hub import snapshot_download

    for repo_id, revision in ((MODEL_ID, MODEL_REVISION), (TOKENIZER_ID, TOKENIZER_REVISION)):
        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            local_dir=target_root / repo_id.split("/")[-1],
            allow_patterns=["config.json", "model.safetensors", "README.md", "LICENSE"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage PolyBob's ignored local Kronos runtime")
    parser.add_argument("command", choices=("pull", "prepare", "status", "verify"))
    parser.add_argument("--source", type=Path, default=Path("Kronos"))
    parser.add_argument("--root", type=Path, default=Path("data/models/kronos"))
    args = parser.parse_args()
    if args.command == "pull":
        pull(args.root)
    elif args.command == "prepare":
        prepare(args.source, args.root)
    lab = KronosLab(KronosLabConfig(root=args.root))
    state = lab.readiness(verify_hashes=args.command == "verify")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    if args.command == "verify" and not state["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
