# Change Logics

- Use a `core / lab / archive` operating model.
- `core` covers the stable daily path: market discovery, realtime ingestion, feature aggregation, strategy catalog, intents, baskets, and risk summaries.
- `lab` covers experimental modules such as BTC demo auto trading and RL experiments; lab modules must stay disabled by default and must not enter the default startup path.
- `archive` keeps historical reports, drafts, and earlier experiments for context without affecting runtime behavior.
- Prefer product changes that reduce daily decision friction, clarify the current opportunity set, and preserve a narrow, reliable default path.
