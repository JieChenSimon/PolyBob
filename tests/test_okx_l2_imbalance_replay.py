from scripts.okx_l2_imbalance_replay import _imbalance, next_target


def test_imbalance_uses_real_top20_depth_values():
    assert _imbalance({"bid_depth_top20": 3.0, "ask_depth_top20": 1.0}) == 0.5


def test_stateful_signal_requires_entry_and_exit_thresholds():
    assert next_target(0.0, 0.70, enter=0.65, exit=0.15) == 1.0
    assert next_target(1.0, 0.20, enter=0.65, exit=0.15) == 1.0
    assert next_target(1.0, 0.10, enter=0.65, exit=0.15) == 0.0
    assert next_target(0.0, -0.70, enter=0.65, exit=0.15) == -1.0


def test_replay_parameter_contract_rejects_unbounded_position_size():
    import asyncio
    from pathlib import Path
    from scripts.okx_l2_imbalance_replay import replay

    async def run():
        try:
            await replay([{}], Path("/tmp"), position_fraction=1.1)
        except ValueError as exc:
            assert "position_fraction" in str(exc)
        else:
            raise AssertionError("invalid position fraction was accepted")

    asyncio.run(run())
