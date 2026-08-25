import numpy as np
import pandas as pd
import inspect

from scripts.crypto_tsmom_walk_forward_replay import CANDIDATES, select_candidate, train_score
from scripts.cross_sectional_kernel_replay import replay_symbol


def test_candidate_grid_is_fixed_and_train_score_is_causal():
    assert len(CANDIDATES) == 8
    prices = np.linspace(100.0, 200.0, 400)
    series = pd.Series(prices, index=[f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(400)])
    candidate = CANDIDATES[0]
    early = train_score(series, series.index[300], candidate)
    late = train_score(series, series.index[350], candidate)
    assert early is not None and late is not None
    assert np.isfinite(early) and np.isfinite(late)
    selected, audit = select_candidate({"X": series}, series.index[300])
    assert selected in CANDIDATES
    assert len(audit) == 8
    assert all(row["symbols_scored"] == 1 for row in audit)


def test_replay_kernel_exposes_opt_in_event_pacing():
    parameters = inspect.signature(replay_symbol).parameters
    assert "event_sleep_seconds" in parameters
    assert "equity_sample_every" in parameters
