"""Fail-closed Kronos adapter for the forecasting lab.

The official source and weights live in ``data/models`` and are ignored by Git.
They are prepared by ``scripts/kronos_models.py`` from a pinned reference
checkout.  No import in this module requires optional forecasting packages until
an enabled forecast is actually requested.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libs.data.trading_calendar import CalendarCoverageError, calendar_for

from .contracts import (
    AssetClass,
    CanonicalBarFrame,
    ForecastArtifact,
    ForecastPoint,
    ForecastStatus,
    ensure_same_length,
    percentile,
)

MODEL_ID = "NeoQuasar/Kronos-base"
MODEL_REVISION = "2b554741eca47781b64468546e77fef3e85130e6"
TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"
MODEL_SHA256 = "abff193acab6db1a0368e9773e75799d11403b6d054ee6d5f0a11aeabc5f4b83"
TOKENIZER_SHA256 = "59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee"
SOURCE_REVISION = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"


class ForecastUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class KronosLabConfig:
    enabled: bool = False
    root: Path = Path("data/models/kronos")
    device: str | None = None
    max_context: int = 512
    paths: int = 3
    temperature: float = 0.8
    top_k: int = 0
    top_p: float = 0.9


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _future_daily_timestamps(frame: CanonicalBarFrame, horizon: int) -> tuple[list[dt.datetime], str]:
    current = frame.bars[-1].timestamp
    try:
        calendar = calendar_for(frame.asset_class.value)
        sessions = calendar.sessions_after(current.date(), horizon)
    except (KeyError, CalendarCoverageError) as exc:
        raise ForecastUnavailable(f"verified trading calendar unavailable: {exc}") from exc
    values = [dt.datetime.combine(day, current.timetz()) for day in sessions]
    return values, calendar.quality


class KronosLab:
    """Lazy singleton-friendly model facade; safe to instantiate in core paths."""

    def __init__(self, config: KronosLabConfig) -> None:
        self.config = config
        self._predictor: Any = None
        self._load_seconds: float | None = None
        self._lock = threading.Lock()

    @property
    def model_dir(self) -> Path:
        return self.config.root / "Kronos-base"

    @property
    def tokenizer_dir(self) -> Path:
        return self.config.root / "Kronos-Tokenizer-base"

    @property
    def runtime_package(self) -> Path:
        return self.config.root / "runtime" / "model"

    def readiness(self, *, verify_hashes: bool = False) -> dict[str, Any]:
        required = {
            "model": self.model_dir / "model.safetensors",
            "tokenizer": self.tokenizer_dir / "model.safetensors",
            "runtime": self.runtime_package / "__init__.py",
            "runtime_manifest": self.config.root / "runtime" / "manifest.json",
        }
        missing = [name for name, path in required.items() if not path.is_file()]
        checksums: dict[str, bool] = {}
        if verify_hashes and not missing:
            checksums = {
                "model": _sha256(required["model"]) == MODEL_SHA256,
                "tokenizer": _sha256(required["tokenizer"]) == TOKENIZER_SHA256,
            }
            try:
                manifest = json.loads(required["runtime_manifest"].read_text())
                checksums["runtime_revision"] = manifest.get("source_revision") == SOURCE_REVISION
                runtime_hashes = manifest.get("runtime_sha256", {})
                checksums["runtime_source"] = all(
                    _sha256(self.runtime_package / name) == expected
                    for name, expected in runtime_hashes.items()
                ) and set(runtime_hashes) == {"__init__.py", "module.py", "kronos.py"}
            except (OSError, ValueError, TypeError):
                checksums["runtime_revision"] = False
                checksums["runtime_source"] = False
        ready = not missing and (not checksums or all(checksums.values()))
        reason = None
        if missing:
            reason = f"missing local artifacts: {', '.join(missing)}"
        elif checksums and not all(checksums.values()):
            reason = "local model checksum mismatch"
        elif not self.config.enabled:
            reason = "lab forecasting is disabled by default"
        return {
            "enabled": self.config.enabled,
            "ready": ready,
            "loaded": self._predictor is not None,
            "reason": reason,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "tokenizer_id": TOKENIZER_ID,
            "tokenizer_revision": TOKENIZER_REVISION,
            "source_revision": SOURCE_REVISION,
            "device": self.config.device or "auto",
            "load_seconds": self._load_seconds,
            "checksums": checksums,
            "promotion_status": "lab_only",
        }

    def _runtime_classes(self):
        package_name = "polybob_kronos_runtime"
        existing = sys.modules.get(package_name)
        if existing is None:
            init_file = self.runtime_package / "__init__.py"
            spec = importlib.util.spec_from_file_location(
                package_name,
                init_file,
                submodule_search_locations=[str(self.runtime_package)],
            )
            if spec is None or spec.loader is None:
                raise ForecastUnavailable("could not construct Kronos runtime module")
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)
            existing = module
        return existing.Kronos, existing.KronosTokenizer, existing.KronosPredictor

    def _load(self):
        if self._predictor is not None:
            return self._predictor
        with self._lock:
            if self._predictor is not None:
                return self._predictor
            state = self.readiness(verify_hashes=False)
            if not state["ready"]:
                raise ForecastUnavailable(str(state["reason"]))
            started = time.perf_counter()
            Kronos, KronosTokenizer, KronosPredictor = self._runtime_classes()
            tokenizer = KronosTokenizer.from_pretrained(str(self.tokenizer_dir))
            model = Kronos.from_pretrained(str(self.model_dir))
            tokenizer.eval()
            model.eval()
            self._predictor = KronosPredictor(
                model,
                tokenizer,
                device=self.config.device,
                max_context=self.config.max_context,
            )
            self._load_seconds = time.perf_counter() - started
        return self._predictor

    def forecast(self, frame: CanonicalBarFrame, *, horizon: int = 5) -> ForecastArtifact:
        if not self.config.enabled:
            raise ForecastUnavailable("lab forecasting is disabled; set ENABLE_LAB_KRONOS_FORECASTING=true")
        if frame.asset_class is AssetClass.PREDICTION_MARKET:
            raise ForecastUnavailable(
                "raw Polymarket probabilities are bounded event contracts; a calibrated probability adapter is required"
            )
        if frame.interval.value != "1d":
            raise ForecastUnavailable("the first integration gate supports daily bars only")
        if not 1 <= horizon <= 20:
            raise ValueError("horizon must be between 1 and 20 bars")
        frame.validate()

        import numpy as np
        import pandas as pd
        import torch

        predictor = self._load()
        context = frame.bars[-self.config.max_context :]
        future, calendar_quality = _future_daily_timestamps(frame, horizon)
        data = {
            "open": [bar.open for bar in context],
            "high": [bar.high for bar in context],
            "low": [bar.low for bar in context],
            "close": [bar.close for bar in context],
        }
        if all(bar.volume is not None for bar in context):
            data["volume"] = [float(bar.volume) for bar in context]
        if all(bar.amount is not None for bar in context):
            data["amount"] = [float(bar.amount) for bar in context]
        input_frame = pd.DataFrame(data)
        x_timestamp = pd.Series(pd.to_datetime([bar.timestamp for bar in context]))
        y_timestamp = pd.Series(pd.to_datetime(future))

        paths: list[Any] = []
        for path_index in range(max(1, self.config.paths)):
            seed = 123 + path_index
            random.seed(seed)
            np.random.seed(seed)
            torch.manual_seed(seed)
            with torch.no_grad():
                paths.append(
                    predictor.predict(
                        input_frame,
                        x_timestamp,
                        y_timestamp,
                        pred_len=horizon,
                        T=self.config.temperature,
                        top_k=self.config.top_k,
                        top_p=self.config.top_p,
                        sample_count=1,
                        verbose=False,
                    )
                )
        ensure_same_length(paths)
        for path in paths:
            for _, row in path.iterrows():
                values = [float(row[name]) for name in ("open", "high", "low", "close")]
                if not all(np.isfinite(value) and value > 0 for value in values):
                    raise ForecastUnavailable("model emitted a non-finite or non-positive OHLC value")
                open_, high, low, close = values
                if low > min(open_, close) or high < max(open_, close):
                    raise ForecastUnavailable("model emitted an invalid OHLC relationship")
        points: list[ForecastPoint] = []
        for index, stamp in enumerate(future):
            opens = [float(path.iloc[index]["open"]) for path in paths]
            highs = [float(path.iloc[index]["high"]) for path in paths]
            lows = [float(path.iloc[index]["low"]) for path in paths]
            closes = [float(path.iloc[index]["close"]) for path in paths]
            points.append(
                ForecastPoint(
                    timestamp=stamp,
                    open_p50=percentile(opens, 0.5),
                    high_p50=percentile(highs, 0.5),
                    low_p50=percentile(lows, 0.5),
                    close_p10=percentile(closes, 0.1),
                    close_p50=percentile(closes, 0.5),
                    close_p90=percentile(closes, 0.9),
                )
            )
        last_close = context[-1].close
        terminal_closes = [float(path.iloc[-1]["close"]) for path in paths]
        expected_return = percentile(terminal_closes, 0.5) / last_close - 1
        up_probability = sum(value > last_close for value in terminal_closes) / len(terminal_closes)
        identity = (
            f"{frame.instrument_id}|{frame.interval.value}|{context[-1].timestamp.isoformat()}|"
            f"{MODEL_REVISION}|{horizon}|{self.config.paths}"
        )
        return ForecastArtifact(
            run_id=hashlib.sha256(identity.encode()).hexdigest()[:16],
            status=ForecastStatus.READY,
            instrument_id=frame.instrument_id,
            asset_class=frame.asset_class,
            interval=frame.interval,
            as_of=context[-1].timestamp,
            source=frame.source,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            tokenizer_id=TOKENIZER_ID,
            tokenizer_revision=TOKENIZER_REVISION,
            context_rows=len(context),
            horizon=horizon,
            feature_mode=frame.feature_mode,
            calendar_quality=calendar_quality,
            paths=len(paths),
            last_close=last_close,
            expected_return=expected_return,
            up_probability=up_probability,
            points=tuple(points),
            generated_at=dt.datetime.now(dt.UTC),
        )


def config_from_settings(settings) -> KronosLabConfig:
    return KronosLabConfig(
        enabled=bool(settings.enable_lab_kronos_forecasting),
        root=Path(settings.polybob_kronos_model_root),
        device=settings.polybob_kronos_device or None,
        paths=max(1, min(int(settings.polybob_kronos_paths), 20)),
    )
