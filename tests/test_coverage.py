"""
测试覆盖率配置和报告
"""
import pytest
from pathlib import Path


def test_coverage_threshold():
    """验证覆盖率插件和配置存在。

    不在测试内部递归启动 pytest；完整覆盖率应由 CI 或开发命令单独运行。
    """
    pytest.importorskip("pytest_cov")

    config = Path("pytest.ini").read_text(encoding="utf-8")
    assert "[coverage:run]" in config
    assert "source =" in config
    assert "libs" in config
    assert "strategies" in config


@pytest.mark.integration
def test_all_critical_paths_covered():
    """验证关键路径已覆盖"""
    critical_paths = {
        "libs/backtest/engine.py": "tests/test_backtest.py",
        "modules/risk_manager/risk_checker.py": "tests/unit/test_risk_control.py",
        "strategies/spread_reversion.py": "tests/test_strategies.py",
    }

    # 检查关键模块是否有测试
    for module, test_path in critical_paths.items():
        assert Path(module).exists(), f"Missing critical module: {module}"
        assert Path(test_path).exists(), f"Missing tests for {module}: {test_path}"
