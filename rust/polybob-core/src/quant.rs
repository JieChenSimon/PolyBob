use numpy::{PyArray1, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

type PyArrayPair<'py> = (Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<f64>>);

fn validate_pair(y: &[f64], x: &[f64]) -> PyResult<()> {
    if y.len() != x.len() {
        return Err(PyValueError::new_err(format!(
            "y and x must have the same length (got {} and {})",
            y.len(),
            x.len()
        )));
    }

    if let Some(index) = y.iter().position(|value| !value.is_finite()) {
        return Err(PyValueError::new_err(format!(
            "y contains a non-finite value at index {index}"
        )));
    }
    if let Some(index) = x.iter().position(|value| !value.is_finite()) {
        return Err(PyValueError::new_err(format!(
            "x contains a non-finite value at index {index}"
        )));
    }

    Ok(())
}

fn compute_rolling_zscore(y: &[f64], x: &[f64], hedge_ratio: f64, lookback: usize) -> Vec<f64> {
    let length = y.len();
    let mut zscores = vec![0.0; length];
    if length == 0 || lookback >= length {
        return zscores;
    }

    let spread: Vec<f64> = y
        .iter()
        .zip(x)
        .map(|(y_value, x_value)| y_value - hedge_ratio * x_value)
        .collect();

    let mut sum = spread[..lookback].iter().sum::<f64>();
    let mut sum_squares = spread[..lookback]
        .iter()
        .map(|value| value * value)
        .sum::<f64>();
    let window_size = lookback as f64;

    for index in lookback..length {
        let mean = sum / window_size;
        // Clamp roundoff below zero while preserving the Python behavior for
        // constant windows: their z-score remains zero.
        let variance = (sum_squares / window_size - mean * mean).max(0.0);
        let standard_deviation = variance.sqrt();
        if standard_deviation > 0.0 {
            zscores[index] = (spread[index] - mean) / standard_deviation;
        }

        if index + 1 < length {
            let leaving = spread[index - lookback];
            let entering = spread[index];
            sum += entering - leaving;
            sum_squares += entering * entering - leaving * leaving;
        }
    }

    zscores
}

fn compute_kalman_hedge_ratio(
    y: &[f64],
    x: &[f64],
    process_noise: f64,
    observation_noise: f64,
) -> (Vec<f64>, Vec<f64>) {
    let mut beta_estimates = Vec::with_capacity(y.len());
    let mut covariance_estimates = Vec::with_capacity(y.len());
    let mut beta = 0.0;
    let mut covariance = 1.0;

    for (&y_value, &x_value) in y.iter().zip(x) {
        let predicted_beta = beta;
        let predicted_covariance = covariance + process_noise;

        if x_value != 0.0 {
            let denominator = x_value * predicted_covariance * x_value + observation_noise;
            let kalman_gain = predicted_covariance * x_value / denominator;
            beta = predicted_beta + kalman_gain * (y_value - predicted_beta * x_value);
            covariance = (1.0 - kalman_gain * x_value) * predicted_covariance;
        } else {
            beta = predicted_beta;
            covariance = predicted_covariance;
        }

        beta_estimates.push(beta);
        covariance_estimates.push(covariance);
    }

    (beta_estimates, covariance_estimates)
}

#[pyfunction(signature = (y, x, hedge_ratio, lookback))]
pub(crate) fn rolling_zscore<'py>(
    py: Python<'py>,
    y: PyReadonlyArray1<'py, f64>,
    x: PyReadonlyArray1<'py, f64>,
    hedge_ratio: f64,
    lookback: usize,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    if !hedge_ratio.is_finite() {
        return Err(PyValueError::new_err("hedge_ratio must be finite"));
    }
    if lookback == 0 {
        return Err(PyValueError::new_err("lookback must be greater than zero"));
    }

    let y = y
        .as_slice()
        .map_err(|_| PyValueError::new_err("y must be a contiguous float64 array"))?;
    let x = x
        .as_slice()
        .map_err(|_| PyValueError::new_err("x must be a contiguous float64 array"))?;
    validate_pair(y, x)?;

    // Own the inputs before releasing the GIL; NumPy memory must not be read
    // while Python code could mutate the source arrays.
    let y = y.to_vec();
    let x = x.to_vec();
    let values = py.allow_threads(move || compute_rolling_zscore(&y, &x, hedge_ratio, lookback));

    Ok(PyArray1::from_vec(py, values))
}

#[pyfunction(signature = (y, x, q=1e-5, r=1e-3))]
pub(crate) fn kalman_hedge_ratio<'py>(
    py: Python<'py>,
    y: PyReadonlyArray1<'py, f64>,
    x: PyReadonlyArray1<'py, f64>,
    q: f64,
    r: f64,
) -> PyResult<PyArrayPair<'py>> {
    if !q.is_finite() || q < 0.0 {
        return Err(PyValueError::new_err(
            "q must be finite and greater than or equal to zero",
        ));
    }
    if !r.is_finite() || r <= 0.0 {
        return Err(PyValueError::new_err(
            "r must be finite and greater than zero",
        ));
    }

    let y = y
        .as_slice()
        .map_err(|_| PyValueError::new_err("y must be a contiguous float64 array"))?;
    let x = x
        .as_slice()
        .map_err(|_| PyValueError::new_err("x must be a contiguous float64 array"))?;
    validate_pair(y, x)?;

    let y = y.to_vec();
    let x = x.to_vec();
    let (betas, covariances) = py.allow_threads(move || compute_kalman_hedge_ratio(&y, &x, q, r));

    Ok((
        PyArray1::from_vec(py, betas),
        PyArray1::from_vec(py, covariances),
    ))
}

#[cfg(test)]
mod tests {
    use super::{compute_kalman_hedge_ratio, compute_rolling_zscore};

    #[test]
    fn rolling_zscore_uses_the_prior_window() {
        let y = [1.0, 2.0, 3.0, 4.0];
        let x = [0.0; 4];
        let result = compute_rolling_zscore(&y, &x, 1.0, 2);

        assert_eq!(result[0], 0.0);
        assert_eq!(result[1], 0.0);
        assert!((result[2] - 3.0).abs() < 1e-12);
        assert!((result[3] - 3.0).abs() < 1e-12);
    }

    #[test]
    fn kalman_zero_observation_preserves_beta_and_increases_covariance() {
        let (betas, covariances) = compute_kalman_hedge_ratio(&[5.0], &[0.0], 1e-5, 1e-3);

        assert_eq!(betas, vec![0.0]);
        assert!((covariances[0] - 1.00001).abs() < 1e-12);
    }
}
