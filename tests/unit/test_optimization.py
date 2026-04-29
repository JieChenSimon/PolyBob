"""参数优化单元测试"""
import numpy as np
import pytest
from libs.quant.optimization import grid_search, walk_forward_analysis


def test_grid_search():
    """测试网格搜索"""
    param_grid = {
        'x': [1, 2, 3],
        'y': [10, 20]
    }

    def objective(params):
        return -(params['x'] - 2)**2 - (params['y'] - 15)**2

    result = grid_search(param_grid, objective, maximize=True)

    assert result.best_params == {'x': 2, 'y': 10}
    assert len(result.all_results) == 6


def test_walk_forward():
    """测试Walk-Forward分析"""
    data = np.arange(100)

    def optimize(train_data):
        return {'mean': train_data.mean()}

    def backtest(test_data, params):
        return -abs(test_data.mean() - params['mean'])

    results = walk_forward_analysis(
        data, train_size=30, test_size=10, step_size=10,
        optimize_func=optimize, backtest_func=backtest
    )

    assert len(results) > 0
    assert 'params' in results[0]
    assert 'score' in results[0]
