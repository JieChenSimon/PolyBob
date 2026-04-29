#!/usr/bin/env python3
"""
测试执行脚本
"""
import sys
import subprocess
from pathlib import Path


def run_unit_tests():
    """运行单元测试"""
    print("=== Running Unit Tests ===")
    result = subprocess.run(
        ["pytest", "tests/unit/", "-v", "--cov=libs", "--cov=strategies"],
        cwd=Path(__file__).parent.parent
    )
    return result.returncode


def run_integration_tests():
    """运行集成测试"""
    print("\n=== Running Integration Tests ===")
    result = subprocess.run(
        ["pytest", "tests/integration/", "-v"],
        cwd=Path(__file__).parent.parent
    )
    return result.returncode


def run_backtest_validation():
    """运行回测验证"""
    print("\n=== Running Backtest Validation ===")
    result = subprocess.run(
        ["pytest", "tests/backtest/", "-v", "-m", "backtest"],
        cwd=Path(__file__).parent.parent
    )
    return result.returncode


def run_performance_tests():
    """运行性能测试"""
    print("\n=== Running Performance Tests ===")
    result = subprocess.run(
        ["pytest", "tests/performance/", "-v", "-m", "performance"],
        cwd=Path(__file__).parent.parent
    )
    return result.returncode


def run_stress_tests():
    """运行压力测试"""
    print("\n=== Running Stress Tests ===")
    result = subprocess.run(
        ["pytest", "tests/stress/", "-v", "-m", "stress"],
        cwd=Path(__file__).parent.parent
    )
    return result.returncode


def run_all_tests():
    """运行所有测试"""
    results = []
    results.append(("Unit Tests", run_unit_tests()))
    results.append(("Integration Tests", run_integration_tests()))
    results.append(("Backtest Validation", run_backtest_validation()))
    results.append(("Performance Tests", run_performance_tests()))
    results.append(("Stress Tests", run_stress_tests()))

    print("\n" + "=" * 50)
    print("Test Summary:")
    print("=" * 50)
    for name, code in results:
        status = "✓ PASSED" if code == 0 else "✗ FAILED"
        print(f"{name}: {status}")

    return 0 if all(code == 0 for _, code in results) else 1


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_type = sys.argv[1]
        if test_type == "unit":
            sys.exit(run_unit_tests())
        elif test_type == "integration":
            sys.exit(run_integration_tests())
        elif test_type == "backtest":
            sys.exit(run_backtest_validation())
        elif test_type == "performance":
            sys.exit(run_performance_tests())
        elif test_type == "stress":
            sys.exit(run_stress_tests())
        else:
            print(f"Unknown test type: {test_type}")
            sys.exit(1)
    else:
        sys.exit(run_all_tests())
