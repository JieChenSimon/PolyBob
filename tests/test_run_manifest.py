"""A result is evidence only if someone can get the same number back.

This project's could not. The insider study reported n=753, then n=667 on a
re-run, because its inputs were an overwritable cache with no timestamps. The
statistics on top were careful; the sample underneath moved. A manifest pins the
three things that decide a result — the observation cut, the code, the parameters
— so a disagreement between two runs can be attributed instead of shrugged at.
"""

from __future__ import annotations

import datetime as dt
import json

from libs.data import run_manifest


def test_the_as_of_is_fixed_once_for_the_whole_run():
    """Taken at the start, not per read.

    A long run that re-reads the clock straddles data refreshes: its early reads
    see less than its late ones, so parts of the same result disagree about what
    was known. That is a look-ahead no test would catch, because every individual
    read looks correct.
    """
    m = run_manifest.pin("demo")
    first = m.as_of
    assert m.as_of is first
    assert m.as_of.tzinfo is not None       # naive times cannot be compared safely


def test_an_explicit_as_of_is_honoured():
    """Replaying an old run means passing its cut back in."""
    cut = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
    assert run_manifest.pin("demo", as_of=cut).as_of == cut


def test_the_code_state_is_recorded():
    m = run_manifest.pin("demo")
    assert "commit" in m.code
    assert "dirty" in m.code


def test_a_dirty_tree_is_not_reproducible():
    """The distinction between "reproducible" and "believed to be reproducible".

    A commit hash means nothing if the working tree had uncommitted edits: the
    hash describes code that did not run. Recording it is what lets a future
    reader know which of the two they are holding.
    """
    m = run_manifest.pin("demo")
    m.code = {"commit": "abc123", "dirty": True, "dirty_files": 4}
    assert m.reproducible is False
    assert any("未提交" in line for line in m.warn_lines())

    m.code = {"commit": "abc123", "dirty": False, "dirty_files": 0}
    assert m.reproducible is True
    assert m.warn_lines() == []


def test_no_git_is_recorded_rather_than_assumed_fine():
    m = run_manifest.pin("demo")
    m.code = {"commit": None, "dirty": False, "dirty_files": 0}
    assert m.reproducible is False
    assert any("无法被别人复现" in line for line in m.warn_lines())


def test_inputs_are_recorded_so_a_disagreement_can_be_attributed():
    """n=753 vs n=667: was it the data or the code? This is what answers that."""
    m = run_manifest.pin("insider_cluster_buy", params={"hold_days": 20})
    m.record_input("daily_bars", symbols=252, rows=331_713, span="2021-07..2026-08")
    m.record_input("insider_filings", events=1141)

    payload = m.to_dict()
    assert payload["inputs"]["daily_bars"]["symbols"] == 252
    assert payload["inputs"]["insider_filings"]["events"] == 1141
    assert payload["params"]["hold_days"] == 20


def test_save_and_load_round_trip(tmp_path):
    result = tmp_path / "insider_results.json"
    result.write_text("{}")
    m = run_manifest.pin("insider_cluster_buy", params={"cost_bps": 10.0})
    m.record_input("daily_bars", rows=5)
    written = m.save(result)

    assert written.name == "insider_results.manifest.json"
    loaded = run_manifest.load(result)
    assert loaded is not None
    assert loaded.experiment == "insider_cluster_buy"
    assert loaded.as_of == m.as_of
    assert loaded.params == {"cost_bps": 10.0}
    assert loaded.inputs["daily_bars"]["rows"] == 5


def test_a_result_with_no_manifest_loads_as_none(tmp_path):
    """``None`` is meaningful: the result predates this discipline.

    Callers must treat it as unverifiable rather than assuming it was fine — the
    whole class of results this project already had were of exactly that kind.
    """
    result = tmp_path / "old_results.json"
    result.write_text("{}")
    assert run_manifest.load(result) is None


def test_a_corrupt_manifest_is_unverifiable_not_a_crash(tmp_path):
    result = tmp_path / "r.json"
    result.write_text("{}")
    (tmp_path / "r.manifest.json").write_text("{ not json")
    assert run_manifest.load(result) is None


def test_the_manifest_is_json_serialisable(tmp_path):
    """It ships next to the evidence, so it has to survive a plain dump."""
    m = run_manifest.pin("demo", params={"symbols": ["AAPL", "MSFT"]})
    text = json.dumps(m.to_dict(), ensure_ascii=False)
    assert "AAPL" in text
    assert json.loads(text)["experiment"] == "demo"


# ------------------------------------------- what counts as a code change
def test_a_new_data_file_is_not_a_code_change():
    """The bug this fixes made the discipline self-defeating.

    An experiment writes its own result and manifest. When ``dirty`` counted every
    untracked path, the *first* run left two new files behind and every run after it
    declared itself unreproducible — permanently, with no way out.
    """
    from libs.data.run_manifest import _is_code

    assert _is_code("data/insider_results.json") is False
    assert _is_code("data/insider_results.manifest.json") is False
    assert _is_code("data/store/daily_bars/symbol=AAPL/x.parquet") is False


def test_a_source_change_is_a_code_change():
    from libs.data.run_manifest import _is_code

    assert _is_code("libs/quant/clustered_inference.py") is True
    assert _is_code("scripts/insider_experiment.py") is True
    assert _is_code("modules/execution_engine/service.py") is True
    assert _is_code("pyproject.toml") is True


def test_the_dirty_sample_names_files_rather_than_only_counting():
    """"638 changes" is unactionable; the first few paths usually settle it."""
    from libs.data.run_manifest import _code_state

    state = _code_state()
    assert isinstance(state["dirty_sample"], list)
    if state["dirty"]:
        assert state["dirty_sample"]
        assert len(state["dirty_sample"]) <= 8


def test_the_warning_says_what_to_do_about_it():
    """A refusal that does not name the remedy gets read as a broken gate."""
    m = run_manifest.pin("demo")
    m.code = {"commit": "abcdef1234", "dirty": True, "dirty_files": 3,
              "dirty_sample": ["libs/quant/x.py"]}
    warning = " ".join(m.warn_lines())
    assert "先提交,再重跑" in warning
    assert "libs/quant/x.py" in warning
