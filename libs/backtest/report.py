"""
Backtest Report Generator - 生成回测报告
"""
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


def generate_html_report(results: dict, equity_curve: List[Tuple[datetime, float]],
                        output_path: str = "backtest_report.html"):
    """生成HTML格式回测报告"""

    # 生成权益曲线数据
    timestamps = [t.isoformat() for t, _ in equity_curve]
    equity_values = [e for _, e in equity_curve]

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Backtest Report</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; }}
        h1 {{ color: #333; }}
        .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 20px 0; }}
        .metric {{ background: #f9f9f9; padding: 15px; border-radius: 5px; }}
        .metric-label {{ color: #666; font-size: 14px; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #333; }}
        .positive {{ color: #22c55e; }}
        .negative {{ color: #ef4444; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Backtest Report</h1>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

        <div class="metrics">
            <div class="metric">
                <div class="metric-label">Total Return</div>
                <div class="metric-value {'positive' if results['total_return'] > 0 else 'negative'}">
                    {results['total_return_pct']:.2f}%
                </div>
            </div>
            <div class="metric">
                <div class="metric-label">Max Drawdown</div>
                <div class="metric-value negative">{results['max_drawdown_pct']:.2f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Sharpe Ratio</div>
                <div class="metric-value">{results.get('sharpe_ratio', 0):.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Number of Trades</div>
                <div class="metric-value">{results['num_trades']}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Initial Capital</div>
                <div class="metric-value">${results['initial_capital']:,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Final Equity</div>
                <div class="metric-value">${results['final_equity']:,.2f}</div>
            </div>
        </div>

        <h2>Equity Curve</h2>
        <div id="equity-chart"></div>

        <script>
            var data = [{{
                x: {timestamps},
                y: {equity_values},
                type: 'scatter',
                mode: 'lines',
                name: 'Equity',
                line: {{ color: '#3b82f6', width: 2 }}
            }}];

            var layout = {{
                title: 'Portfolio Equity Over Time',
                xaxis: {{ title: 'Time' }},
                yaxis: {{ title: 'Equity ($)' }},
                hovermode: 'x unified'
            }};

            Plotly.newPlot('equity-chart', data, layout);
        </script>
    </div>
</body>
</html>"""

    Path(output_path).write_text(html)
    return output_path


def generate_markdown_report(results: dict, output_path: str = "backtest_report.md"):
    """生成Markdown格式回测报告"""

    md = f"""# Backtest Report

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Performance Metrics

| Metric | Value |
|--------|-------|
| Initial Capital | ${results['initial_capital']:,.2f} |
| Final Equity | ${results['final_equity']:,.2f} |
| Total Return | {results['total_return_pct']:.2f}% |
| Max Drawdown | {results['max_drawdown_pct']:.2f}% |
| Sharpe Ratio | {results.get('sharpe_ratio', 0):.2f} |
| Number of Trades | {results['num_trades']} |
| Total Fees | ${results['total_fees']:.2f} |

## Summary

{'✅ Profitable' if results['total_return'] > 0 else '❌ Loss'}

- Return: **{results['total_return_pct']:.2f}%**
- Risk-adjusted return (Sharpe): **{results.get('sharpe_ratio', 0):.2f}**
- Maximum drawdown: **{results['max_drawdown_pct']:.2f}%**
"""

    Path(output_path).write_text(md)
    return output_path
