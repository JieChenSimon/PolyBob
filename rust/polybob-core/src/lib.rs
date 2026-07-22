mod backtest;
mod quant;
mod risk;

use pyo3::prelude::*;

#[pymodule]
fn polybob_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(quant::rolling_zscore, module)?)?;
    module.add_function(wrap_pyfunction!(quant::kalman_hedge_ratio, module)?)?;
    module.add_function(wrap_pyfunction!(risk::risk_metrics, module)?)?;
    module.add_function(wrap_pyfunction!(risk::max_drawdown, module)?)?;
    module.add_function(wrap_pyfunction!(backtest::slippage_batch, module)?)?;
    Ok(())
}
