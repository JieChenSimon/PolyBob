use numpy::{PyArray1, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

fn validate_finite(name: &str, values: &[f64]) -> PyResult<()> {
    if let Some(index) = values.iter().position(|value| !value.is_finite()) {
        return Err(PyValueError::new_err(format!(
            "{name} contains a non-finite value at index {index}"
        )));
    }
    Ok(())
}

fn validate_same_length(arrays: &[(&str, &[f64])]) -> PyResult<()> {
    if arrays.is_empty() {
        return Ok(());
    }
    let expected = arrays[0].1.len();
    for (name, values) in arrays.iter().skip(1) {
        if values.len() != expected {
            return Err(PyValueError::new_err(format!(
                "{name} length must match prices length (got {} and {expected})",
                values.len()
            )));
        }
    }
    Ok(())
}

pub(crate) fn compute_slippage_batch(
    prices: &[f64],
    sizes: &[f64],
    market_depth: f64,
    base_slippage_bps: f64,
    volatilities: &[f64],
) -> Vec<f64> {
    prices
        .iter()
        .zip(sizes)
        .zip(volatilities)
        .map(|((&price, &size), &volatility)| {
            let impact = size / market_depth;
            let slippage_bps = base_slippage_bps + impact * volatility * 10_000.0;
            price * (slippage_bps / 10_000.0)
        })
        .collect()
}

#[pyfunction(signature = (prices, sizes, market_depth, base_slippage_bps, volatilities))]
pub(crate) fn slippage_batch<'py>(
    py: Python<'py>,
    prices: PyReadonlyArray1<'py, f64>,
    sizes: PyReadonlyArray1<'py, f64>,
    market_depth: f64,
    base_slippage_bps: f64,
    volatilities: PyReadonlyArray1<'py, f64>,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    if !market_depth.is_finite() || market_depth <= 0.0 {
        return Err(PyValueError::new_err(
            "market_depth must be finite and greater than zero",
        ));
    }
    if !base_slippage_bps.is_finite() {
        return Err(PyValueError::new_err("base_slippage_bps must be finite"));
    }

    let prices = prices
        .as_slice()
        .map_err(|_| PyValueError::new_err("prices must be a contiguous float64 array"))?;
    let sizes = sizes
        .as_slice()
        .map_err(|_| PyValueError::new_err("sizes must be a contiguous float64 array"))?;
    let volatilities = volatilities
        .as_slice()
        .map_err(|_| PyValueError::new_err("volatilities must be a contiguous float64 array"))?;
    validate_same_length(&[
        ("prices", prices),
        ("sizes", sizes),
        ("volatilities", volatilities),
    ])?;
    validate_finite("prices", prices)?;
    validate_finite("sizes", sizes)?;
    validate_finite("volatilities", volatilities)?;

    let prices = prices.to_vec();
    let sizes = sizes.to_vec();
    let volatilities = volatilities.to_vec();
    let values = py.allow_threads(move || {
        compute_slippage_batch(
            &prices,
            &sizes,
            market_depth,
            base_slippage_bps,
            &volatilities,
        )
    });

    Ok(PyArray1::from_vec(py, values))
}

#[cfg(test)]
mod tests {
    use super::compute_slippage_batch;

    #[test]
    fn slippage_batch_matches_vectorized_python_formula() {
        let prices = [100.0, 50.0];
        let sizes = [1000.0, 500.0];
        let volatilities = [0.02, 0.04];
        let result = compute_slippage_batch(&prices, &sizes, 100_000.0, 10.0, &volatilities);

        assert!((result[0] - 0.12).abs() < 1e-12);
        assert!((result[1] - 0.06).abs() < 1e-12);
    }
}
