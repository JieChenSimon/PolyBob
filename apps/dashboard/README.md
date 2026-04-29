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

The dashboard is available at http://localhost:3000 unless Next.js selects another free port.

## Configuration

The dashboard reads the API base URL from `NEXT_PUBLIC_API_BASE_URL`.
When unset, it uses `http://localhost:8000`.

## Validation

```bash
npm run build
```

## Tech Stack

- Next.js 15
- React 19
- TypeScript
- Tailwind CSS
- Recharts
