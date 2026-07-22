use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use numpy::PyReadonlyArray1;

fn validate_finite(name: &str, values: &[f64]) -> PyResult<()> {
    if let Some(index) = values.iter().position(|value| !value.is_finite()) {
        return Err(PyValueError::new_err(format!(
            "{name} contains a non-finite value at index {index}"
        )));
    }
    Ok(())
}

fn percentile_linear(values: &[f64], percentile: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }

    let mut sorted = values.to_vec();
    sorted.sort_by(|left, right| left.total_cmp(right));

    if sorted.len() == 1 {
        return sorted[0];
    }

    let rank = percentile / 100.0 * (sorted.len() - 1) as f64;
    let lower = rank.floor() as usize;
    let upper = rank.ceil() as usize;
    if lower == upper {
        sorted[lower]
    } else {
        let weight = rank - lower as f64;
        sorted[lower] * (1.0 - weight) + sorted[upper] * weight
    }
}

fn mean(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    values.iter().sum::<f64>() / values.len() as f64
}

fn population_std(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let average = mean(values);
    let variance = values
        .iter()
        .map(|value| {
            let delta = value - average;
            delta * delta
        })
        .sum::<f64>()
        / values.len() as f64;
    variance.max(0.0).sqrt()
}

pub(crate) fn compute_max_drawdown(equity_curve: &[f64]) -> (f64, usize, usize) {
    if equity_curve.is_empty() {
        return (0.0, 0, 0);
    }

    let mut peak = equity_curve[0];
    let mut peak_index = 0usize;
    let mut max_drawdown = 0.0;
    let mut max_peak_index = 0usize;
    let mut max_trough_index = 0usize;

    for (index, &value) in equity_curve.iter().enumerate() {
        if value > peak {
            peak = value;
            peak_index = index;
        }

        let drawdown = if peak > 0.0 {
            (peak - value) / peak
        } else {
            0.0
        };
        if drawdown > max_drawdown {
            max_drawdown = drawdown;
            max_peak_index = peak_index;
            max_trough_index = index;
        }
    }

    (max_drawdown, max_peak_index, max_trough_index)
}

fn compute_var(returns: &[f64], confidence: f64) -> f64 {
    if returns.is_empty() {
        return 0.0;
    }
    -percentile_linear(returns, (1.0 - confidence) * 100.0)
}

fn compute_cvar(returns: &[f64], confidence: f64) -> f64 {
    if returns.is_empty() {
        return 0.0;
    }

    let value_at_risk = compute_var(returns, confidence);
    let threshold = -value_at_risk;
    let mut total = 0.0;
    let mut count = 0usize;
    for &value in returns {
        if value <= threshold {
            total += value;
            count += 1;
        }
    }

    if count == 0 {
        0.0
    } else {
        -(total / count as f64)
    }
}

fn compute_sharpe_ratio(returns: &[f64], periods_per_year: f64) -> f64 {
    let standard_deviation = population_std(returns);
    if returns.is_empty() || standard_deviation == 0.0 {
        return 0.0;
    }
    mean(returns) / standard_deviation * periods_per_year.sqrt()
}

fn compute_sortino_ratio(returns: &[f64], periods_per_year: f64) -> f64 {
    if returns.is_empty() {
        return 0.0;
    }

    let downside_returns: Vec<f64> = returns
        .iter()
        .copied()
        .filter(|value| *value < 0.0)
        .collect();
    let downside_std = population_std(&downside_returns);
    if downside_returns.is_empty() || downside_std == 0.0 {
        return 0.0;
    }

    mean(returns) / downside_std * periods_per_year.sqrt()
}

fn compute_annual_return(equity_curve: &[f64], periods_per_year: f64) -> f64 {
    if equity_curve.is_empty() || equity_curve[0] == 0.0 {
        return 0.0;
    }

    let total_return = (equity_curve[equity_curve.len() - 1] - equity_curve[0]) / equity_curve[0];
    let base = 1.0 + total_return;
    if base <= 0.0 {
        return -1.0;
    }

    base.powf(periods_per_year / equity_curve.len() as f64) - 1.0
}

#[pyfunction(signature = (equity_curve))]
pub(crate) fn max_drawdown(
    equity_curve: PyReadonlyArray1<'_, f64>,
) -> PyResult<(f64, usize, usize)> {
    let equity_curve = equity_curve
        .as_slice()
        .map_err(|_| PyValueError::new_err("equity_curve must be a contiguous float64 array"))?;
    validate_finite("equity_curve", equity_curve)?;
    Ok(compute_max_drawdown(equity_curve))
}

#[pyfunction(signature = (returns, equity_curve, confidence=0.95, periods_per_year=252.0))]
pub(crate) fn risk_metrics<'py>(
    py: Python<'py>,
    returns: PyReadonlyArray1<'py, f64>,
    equity_curve: PyReadonlyArray1<'py, f64>,
    confidence: f64,
    periods_per_year: f64,
) -> PyResult<Bound<'py, PyDict>> {
    if !confidence.is_finite() || confidence <= 0.0 || confidence >= 1.0 {
        return Err(PyValueError::new_err(
            "confidence must be finite and between zero and one",
        ));
    }
    if !periods_per_year.is_finite() || periods_per_year <= 0.0 {
        return Err(PyValueError::new_err(
            "periods_per_year must be finite and greater than zero",
        ));
    }

    let returns = returns
        .as_slice()
        .map_err(|_| PyValueError::new_err("returns must be a contiguous float64 array"))?;
    let equity_curve = equity_curve
        .as_slice()
        .map_err(|_| PyValueError::new_err("equity_curve must be a contiguous float64 array"))?;
    validate_finite("returns", returns)?;
    validate_finite("equity_curve", equity_curve)?;

    let returns = returns.to_vec();
    let equity_curve = equity_curve.to_vec();
    let metrics = py.allow_threads(move || {
        let var_95 = compute_var(&returns, confidence);
        let cvar_95 = compute_cvar(&returns, confidence);
        let (max_drawdown, peak_index, trough_index) = compute_max_drawdown(&equity_curve);
        let sharpe_ratio = compute_sharpe_ratio(&returns, periods_per_year);
        let sortino_ratio = compute_sortino_ratio(&returns, periods_per_year);
        let annual_return = compute_annual_return(&equity_curve, periods_per_year);
        let calmar_ratio = if max_drawdown == 0.0 {
            0.0
        } else {
            annual_return / max_drawdown
        };

        (
            var_95,
            cvar_95,
            max_drawdown,
            peak_index,
            trough_index,
            sharpe_ratio,
            sortino_ratio,
            calmar_ratio,
        )
    });

    let dict = PyDict::new(py);
    dict.set_item("var_95", metrics.0)?;
    dict.set_item("cvar_95", metrics.1)?;
    dict.set_item("max_drawdown", metrics.2)?;
    dict.set_item("max_drawdown_peak_index", metrics.3)?;
    dict.set_item("max_drawdown_trough_index", metrics.4)?;
    dict.set_item("sharpe_ratio", metrics.5)?;
    dict.set_item("sortino_ratio", metrics.6)?;
    dict.set_item("calmar_ratio", metrics.7)?;
    Ok(dict)
}

#[cfg(test)]
mod tests {
    use super::{
        compute_cvar, compute_max_drawdown, compute_sharpe_ratio, compute_sortino_ratio,
        compute_var, percentile_linear,
    };

    #[test]
    fn percentile_matches_numpy_linear_interpolation_for_small_arrays() {
        let values = [-0.10, -0.03, 0.01, 0.04, 0.08];
        assert!((percentile_linear(&values, 5.0) - -0.086).abs() < 1e-12);
    }

    #[test]
    fn risk_metrics_follow_existing_python_semantics() {
        let returns = [-0.10, -0.03, 0.01, 0.04, 0.08];
        assert!((compute_var(&returns, 0.95) - 0.086).abs() < 1e-12);
        assert!((compute_cvar(&returns, 0.95) - 0.10).abs() < 1e-12);
        assert!(compute_sharpe_ratio(&returns, 252.0).is_finite());
        assert!(compute_sortino_ratio(&returns, 252.0).is_finite());
    }

    #[test]
    fn max_drawdown_returns_peak_and_trough_indexes() {
        let (drawdown, peak_index, trough_index) =
            compute_max_drawdown(&[100.0, 120.0, 90.0, 130.0, 80.0]);
        assert!((drawdown - 50.0 / 130.0).abs() < 1e-12);
        assert_eq!(peak_index, 3);
        assert_eq!(trough_index, 4);
    }
}
