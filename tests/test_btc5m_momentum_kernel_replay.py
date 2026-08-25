from scripts.btc5m_momentum_kernel_replay import (
    COST_MULTIPLES,
    CPU_TARGET,
    PRE_REGISTERED,
    CpuBudgetThrottle,
)


def test_momentum_replay_family_is_small_and_pre_registered():
    assert PRE_REGISTERED == ((12, 36), (36, 72), (12, 72))
    assert COST_MULTIPLES == (1.0, 2.0, 3.0)
    assert len(PRE_REGISTERED) * len(COST_MULTIPLES) == 9


def test_cpu_budget_throttle_is_bounded():
    throttle = CpuBudgetThrottle(target=1.0)
    assert throttle.target == 0.50
    assert CPU_TARGET == 0.45
    assert 0.05 <= throttle.target <= 0.50
