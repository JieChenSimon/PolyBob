'use client';

import { useEffect, useMemo, useState } from 'react';

function buildMarketSlug(now: Date) {
  const timestamp = Math.floor(now.getTime() / 1000);
  const windowStart = timestamp - (timestamp % 300);
  return `btc-updown-5m-${windowStart}`;
}

function buildMarketName(now: Date) {
  const formatter = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
    timeZoneName: 'short',
  });
  return `Bitcoin Up or Down - ${formatter.format(now)}`;
}

export default function PolymarketOfficialEmbed() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 5_000);
    return () => window.clearInterval(timer);
  }, []);

  const marketSlug = useMemo(() => buildMarketSlug(now), [now]);
  const marketName = useMemo(() => buildMarketName(now), [now]);
  const refreshBucket = Math.floor(now.getTime() / 15_000);
  const marketUrl = `https://polymarket.com/event/${marketSlug}`;
  const embedUrl = `https://embed.polymarket.com/market?market=${marketSlug}&theme=light&height=300`;
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: marketName,
    description: 'Prediction market: Bitcoin Up or Down on Polymarket.',
    url: marketUrl,
    publisher: {
      '@type': 'Organization',
      name: 'Polymarket',
      url: 'https://polymarket.com',
    },
  };

  return (
    <section className="panel overflow-hidden">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <div className="flex flex-col gap-2 border-b border-stone-200 px-5 py-4 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
            Official Embed
          </div>
          <h3 className="mt-1 text-lg font-bold text-stone-950">
            Polymarket 官方市场窗口
          </h3>
        </div>
        <a
          href={marketUrl}
          target="_blank"
          rel="noopener"
          className="text-sm font-semibold text-sky-700 hover:text-sky-900"
        >
          在 Polymarket 打开
        </a>
      </div>

      <div className="grid gap-4 px-5 py-5 md:grid-cols-[400px,minmax(0,1fr)] md:items-stretch">
        <figure
          className="polymarket-embed relative m-0 block w-full max-w-[400px] overflow-hidden rounded-lg border border-stone-200 bg-white"
          id={`polymarket-${marketSlug}`}
          aria-label={`Polymarket prediction market: ${marketName}`}
          itemScope
          itemType="https://schema.org/WebPage"
        >
          <iframe
            key={`${marketSlug}-${refreshBucket}`}
            title={`${marketName} - Polymarket Prediction Market`}
            src={embedUrl}
            className="block h-[300px] w-full max-w-[400px]"
            width="400"
            height="300"
            frameBorder="0"
            {...{ allowtransparency: 'true' }}
          />
          <a
            href={marketUrl}
            aria-label="View on Polymarket"
            target="_blank"
            rel="noopener"
            className="absolute right-5 top-4 z-10 h-6 w-[120px]"
          />
          <figcaption className="sr-only">
            <strong>{marketName}</strong>
            <br />
            View full market and trade on Polymarket.
          </figcaption>
        </figure>
        <div className="grid content-center gap-3 rounded-lg border border-stone-200 bg-stone-50 px-4 py-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
              Embedded Market
            </div>
            <div className="mono mt-1 break-all text-sm font-semibold text-stone-900">
              {marketSlug}
            </div>
          </div>
          <p className="text-sm leading-6 text-stone-600">
            这个窗口使用 Polymarket 官方 embed。PolyBob 每 5 秒检查当前 5 分钟市场窗口，并每 15 秒重新加载 iframe，避免官方窗口停留在旧快照；盘口结论仍以下方 CLOB 真实盘口为准。
          </p>
        </div>
      </div>
    </section>
  );
}
