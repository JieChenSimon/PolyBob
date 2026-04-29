"""
参数优化框架
实现网格搜索和Walk-Forward分析
"""
import numpy as np
from typing import Dict, List, Any, Callable, Tuple
from itertools import product
from dataclasses import dataclass


@dataclass
class OptimizationResult:
    """优化结果"""
    best_params: Dict[str, Any]
    best_score: float
    all_results: List[Tuple[Dict[str, Any], float]]


def grid_search(
    param_grid: Dict[str, List[Any]],
    objective_func: Callable[[Dict[str, Any]], float],
    maximize: bool = True
) -> OptimizationResult:
    """
    网格搜索优化

    Args:
        param_grid: 参数网格 {'param_name': [val1, val2, ...]}
        objective_func: 目标函数，输入参数字典，返回评分
        maximize: True=最大化, False=最小化

    Returns:
        OptimizationResult
    """
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    best_score = float('-inf') if maximize else float('inf')
    best_params = None
    all_results = []

    for values in product(*param_values):
        params = dict(zip(param_names, values))
        score = objective_func(params)
        all_results.append((params.copy(), score))

        if (maximize and score > best_score) or (not maximize and score < best_score):
            best_score = score
            best_params = params

    return OptimizationResult(
        best_params=best_params,
        best_score=best_score,
        all_results=all_results
    )


def walk_forward_analysis(
    data: np.ndarray,
    train_size: int,
    test_size: int,
    step_size: int,
    optimize_func: Callable[[np.ndarray], Dict[str, Any]],
    backtest_func: Callable[[np.ndarray, Dict[str, Any]], float]
) -> List[Dict[str, Any]]:
    """
    Walk-Forward分析

    Args:
        data: 时间序列数据
        train_size: 训练窗口大小
        test_size: 测试窗口大小
        step_size: 滚动步长
        optimize_func: 优化函数，输入训练数据，返回最优参数
        backtest_func: 回测函数，输入测试数据和参数，返回评分

    Returns:
        每个窗口的结果列表
    """
    results = []
    n = len(data)

    start = 0
    while start + train_size + test_size <= n:
        train_end = start + train_size
        test_end = train_end + test_size

        train_data = data[start:train_end]
        test_data = data[train_end:test_end]

        # 优化参数
        params = optimize_func(train_data)

        # 测试
        score = backtest_func(test_data, params)

        results.append({
            'train_start': start,
            'train_end': train_end,
            'test_start': train_end,
            'test_end': test_end,
            'params': params,
            'score': score
        })

        start += step_size

    return results
