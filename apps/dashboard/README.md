# PolyBob Dashboard

Personal market research and paper execution dashboard for PolyBob.

## Role

- Daily brief for market research, signal review, and paper execution readiness.
- Personal workbench UI, not a public SaaS dashboard.
- Lab auto-trading surfaces remain disabled by default unless the backend enables them explicitly.

## Development

```bash
cd apps/dashboard
npm install
npm run dev
```

The dashboard is available at http://localhost:13001 by default.
Override it with `POLYBOB_DASHBOARD_PORT`.

## Configuration

The dashboard reads the API base URL from `NEXT_PUBLIC_API_BASE_URL`.
`NEXT_PUBLIC_API_BASE` is still accepted for older local setups.
When unset, it uses `http://localhost:18000`.

## Validation

```bash
npm test
npm run build
```

## Tech Stack

- Next.js 15
- React 19
- TypeScript
- Tailwind CSS
- Recharts
