# PolyBob Web Dashboard

A cyberpunk terminal-inspired real-time trading dashboard for Polymarket.

## Features

- 🖥️ **Terminal Aesthetic**: Monochrome design with neon green accents
- 📊 **Real-time Charts**: Live price and spread visualization
- ⚠️ **Anomaly Detection**: Visual alerts for unusual market conditions
- 🔄 **Auto-refresh**: Polls API every 5 seconds for latest data
- 📱 **Responsive**: Works on desktop and tablet

## Installation

```bash
cd apps/dashboard

# Install dependencies
npm install

# Start development server
npm run dev
```

The dashboard will be available at http://localhost:3001

## Configuration

The dashboard connects to the PolyBob API at `http://localhost:8000` by default.

To change the API endpoint, edit `app/page.tsx`:

```typescript
const API_BASE = 'http://your-api-url:8000';
```

## Usage

1. Start the PolyBob API server first
2. Start the dashboard with `npm run dev`
3. Open http://localhost:3001 in your browser
4. Select markets from the left sidebar to view details

## Design Philosophy

The dashboard uses a **Cyberpunk Terminal** aesthetic:

- **Typography**: JetBrains Mono for that authentic terminal feel
- **Colors**: Deep black backgrounds with neon green/cyan accents
- **Effects**: CRT scanlines, glitch animations on alerts, ASCII borders
- **Layout**: Professional trading terminal with clear information hierarchy

## Build for Production

```bash
npm run build
npm start
```

## Tech Stack

- Next.js 15
- React 19
- TypeScript
- Tailwind CSS
- Recharts
