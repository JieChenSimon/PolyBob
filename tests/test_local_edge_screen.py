import numpy as np

from scripts.local_edge_screen import unresolved_jump


def test_local_edge_screen_rejects_unresolved_price_jump():
    assert unresolved_jump(np.array([1.0, 2.0]), 1.5)
    assert not unresolved_jump(np.array([1.0, 1.2, 1.1]), 1.5)
