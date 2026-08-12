#!/usr/bin/env python3
"""One-step memory/throughput probe for the public Kronos-large architecture.

This does not claim to reproduce the unavailable model. It initializes random
weights, runs one full training step, and reports the measured feasibility of
the architecture on the current machine.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path


def load_runtime(root: Path):
    package = "polybob_kronos_large_benchmark"
    model_root = root / "runtime" / "model"
    spec = importlib.util.spec_from_file_location(
        package,
        model_root / "__init__.py",
        submodule_search_locations=[str(model_root)],
    )
    if spec is None or spec.loader is None:
        raise SystemExit("prepare the runtime with scripts/kronos_models.py prepare")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/models/kronos"))
    parser.add_argument("--config", type=Path, default=Path("config/kronos_large_research.json"))
    parser.add_argument("--device", default="mps")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sequence-length", type=int, default=512)
    args = parser.parse_args()
    if args.batch_size < 1 or args.sequence_length < 2:
        raise SystemExit("batch size must be positive and sequence length at least two")

    import torch

    config = json.loads(args.config.read_text())
    runtime = load_runtime(args.root)
    fields = (
        "s1_bits", "s2_bits", "n_layers", "d_model", "n_heads", "ff_dim",
        "ffn_dropout_p", "attn_dropout_p", "resid_dropout_p", "token_dropout_p", "learn_te",
    )
    model = runtime.Kronos(**{name: config[name] for name in fields}).to(args.device).train()
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"]
    )
    shape = (args.batch_size, args.sequence_length)
    s1 = torch.randint(0, 1024, shape, device=args.device)
    s2 = torch.randint(0, 1024, shape, device=args.device)
    stamp = torch.zeros((*shape, 5), device=args.device)
    target1 = torch.randint(0, 1024, shape, device=args.device)
    target2 = torch.randint(0, 1024, shape, device=args.device)

    started = time.perf_counter()
    logits = model(s1, s2, stamp)
    loss, _, _ = model.head.compute_loss(logits[0], logits[1], target1, target2)
    loss.backward()
    optimizer.step()
    elapsed = time.perf_counter() - started
    result = {
        "status": "architecture_probe_only",
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "device": args.device,
        "batch_size": args.batch_size,
        "sequence_length": args.sequence_length,
        "step_seconds": elapsed,
        "tokens_per_second": args.batch_size * args.sequence_length / elapsed,
        "loss": float(loss.item()),
    }
    if args.device == "mps":
        result.update({
            "mps_allocated_gib": torch.mps.current_allocated_memory() / 2**30,
            "mps_driver_gib": torch.mps.driver_allocated_memory() / 2**30,
            "mps_recommended_max_gib": torch.mps.recommended_max_memory() / 2**30,
        })
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
