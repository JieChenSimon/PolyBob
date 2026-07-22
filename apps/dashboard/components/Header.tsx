'use client';

interface HeaderProps {
  isConnected: boolean;
  lastUpdate: Date | null;
  marketCount: number;
  featureCount: number;
}

export default function Header({
  isConnected,
  lastUpdate,
  marketCount,
  featureCount,
}: HeaderProps) {
  const formatTime = (value: Date | null) => {
    if (!value) {
      return '--:--:--';
    }

    return value.toLocaleTimeString('en-GB', {
      hour12: false,
    });
  };

  return (
    <header className="mx-auto w-full max-w-shell px-5 pt-5 md:px-8 md:pt-8">
      <div className="panel overflow-hidden">
        <div className="grid gap-6 px-6 py-6 md:grid-cols-[minmax(0,1.4fr),minmax(0,0.8fr)] md:px-8 md:py-8">
          <div>
            <span className="eyebrow">Realtime Market Desk</span>
            <h1 className="mt-4 text-4xl font-bold tracking-[-0.06em] text-stone-900 md:text-6xl">
              PolyBob
              <span className="block text-stone-500">Polymarket Control Room</span>
            </h1>
            <p className="mt-4 max-w-3xl text-sm leading-6 text-stone-600 md:text-base">
              左侧先看市场列表，优先关注问题本身、流动性和 spread。选中一个市场后，
              右侧会显示盘口、价格变化和一份简洁的阅读指南，帮助你判断它现在是“可观察”还是“值得介入”。
            </p>
          </div>

          <div className="grid gap-3 md:justify-self-end">
            <div className="metric-panel">
              <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                System Status
              </div>
              <div className="mt-3 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span
                    className={`h-3 w-3 rounded-full ${
                      isConnected ? 'bg-emerald-500 shadow-[0_0_0_6px_rgba(16,185,129,0.14)]' : 'bg-rose-500 shadow-[0_0_0_6px_rgba(244,63,94,0.14)]'
                    }`}
                  />
                  <div>
                    <div className="text-sm font-semibold text-stone-900">
                      {isConnected ? 'API Connected' : 'API Disconnected'}
                    </div>
                    <div className="mono text-xs text-stone-500">
                      Last refresh {formatTime(lastUpdate)}
                    </div>
                  </div>
                </div>
                <div className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-600">
                  {featureCount}/{marketCount} loaded
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="metric-panel">
                <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                  Markets
                </div>
                <div className="mt-2 text-3xl font-bold tracking-[-0.05em] text-stone-900">
                  {marketCount}
                </div>
                <div className="mt-1 text-sm text-stone-500">tracked in watchlist</div>
              </div>
              <div className="metric-panel">
                <div className="text-xs font-medium uppercase tracking-[0.14em] text-stone-500">
                  Features
                </div>
                <div className="mt-2 text-3xl font-bold tracking-[-0.05em] text-stone-900">
                  {featureCount}
                </div>
                <div className="mt-1 text-sm text-stone-500">ready for review</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
