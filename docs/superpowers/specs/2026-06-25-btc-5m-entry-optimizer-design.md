# BTC 5m Entry Optimizer Design

## Goal

Build an explainable entry optimizer for the Polymarket BTC five-minute Up/Down module. It must produce three aligned outputs from the same calculation: a core conclusion, price zones, and a complete execution suggestion.

## Scope

The first version is for the BTC five-minute Up/Down workbench only. It uses real Polymarket CLOB order books, the Polymarket target price, and the BTC reference price already present in the workbench. It does not execute real trades and does not use fabricated data.

## Decision Model

The model is layered.

1. Survival constraints reject bad setups before scoring: missing real order book, stale order book, wide spread, low top depth, missing target price, missing BTC reference price, missing expiry, or near-expiry windows.
2. Expected value ranks eligible outcomes. For a binary share bought at ask price, first-order EV is `p_win - entry_price - cost_penalty`.
3. Fractional Kelly sizes the signal. The raw Kelly fraction is `(p_win - entry_price) / (1 - entry_price)`, clamped to non-negative values and multiplied by a conservative fraction such as `0.25`.

## Probability Estimate

`p_win` is intentionally explainable rather than black-box.

- Price component: compare BTC reference price to Polymarket target price. The farther current BTC is above target, the higher UP probability; the farther below, the higher DOWN probability.
- Market component: use Polymarket Up and Down order-book midpoints as the market-implied probability.
- Blend: first version uses a weighted blend of price component and market component, then clamps to avoid false certainty.

## Entry Outputs

Each outcome includes:

- `entry_decision`: `enter`, `watch`, or `avoid`.
- `entry_band`: `enter_below`, `watch_below`, and `avoid_above`.
- `expected_value`: net EV after cost penalty.
- `win_probability`: model probability for the outcome.
- `kelly_fraction`: conservative fractional Kelly suggestion.
- `max_acceptable_price`: highest buy price that still clears the EV threshold.
- `risk_notes`: reason codes that explain the decision.

The workbench-level conclusion selects the highest EV eligible outcome. If neither outcome clears the survival and EV gates, the workbench stays `no_trade`.

## UI

The Polymarket page should keep one core conclusion visible in the main window. Details can show the three forms:

- one-line conclusion,
- price zones,
- execution suggestion with probability, EV, and Kelly fraction.

## Error Handling

Missing target price or missing BTC reference price must produce `no_trade`; it must not fall back to fake values. If an external data source is down, the existing error diagnosis remains responsible for explaining the data failure.

## Testing

Backend tests must cover:

- missing target price rejects trading,
- a favorable UP setup produces an `enter` recommendation,
- a high ask price converts the same setup to `watch` or `avoid`,
- Kelly is capped by configuration,
- price bands are internally consistent.

Frontend tests must cover parsing the new entry optimizer fields.
