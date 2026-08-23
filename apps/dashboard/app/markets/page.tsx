import { Suspense } from 'react';
import BestOpportunity from '@/components/BestOpportunity';
import GlobalSentimentPanel from '@/components/GlobalSentimentPanel';
import MarketNewsTerminal from '@/components/MarketNewsTerminal';
import MarketsWorkspace from '@/components/MarketsWorkspace';
import ForecastBatchScanner from '@/components/ForecastBatchScanner';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';
import Link from 'next/link';

export default function MarketsPage() {
  return (
    <>
      <WorkbenchPageHeader eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }} title={{ zh: '预测市场', en: 'Prediction Markets' }} description={{ zh: '查看 Polymarket 事件标的、盘口、流动性和市场数据可信度。股票与加密资产在各自工作区独立分析。', en: 'Review Polymarket event instruments, order books, liquidity and data trust. Equities and crypto live in dedicated workspaces.' }} />

      <main className="mx-auto mt-4 w-full max-w-shell px-5 pb-10 md:mt-5 md:px-8">
        <section className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Asset workspaces">
          {[
            ['/us-equities', '美股 / US Equities'],
            ['/a-shares', 'A股 / A-Shares'],
            ['/crypto/altcoin-discovery', '加密货币 / Crypto'],
            ['/btc-5m', 'BTC 5分钟 / BTC 5m'],
          ].map(([href, label]) => (
            <Link key={href} href={href} className="rounded-lg border border-stone-200 bg-white px-4 py-3 text-sm font-semibold text-stone-700 transition hover:border-sky-400 hover:text-sky-700">
              {label} →
            </Link>
          ))}
        </section>
        <Suspense fallback={<div className="mb-6 h-28 rounded-xl border-l-4 border-stone-200 bg-stone-50" />}>
          <BestOpportunity
            domain="a_share"
            title={{ zh: 'A股今天要回避哪些', en: 'Which A-shares to avoid today' }}
          />
        </Suspense>
        <GlobalSentimentPanel />
        <MarketNewsTerminal />
        <MarketsWorkspace />
        <ForecastBatchScanner domain="a_share" symbols={['600519', '000858', '601318', '300750']} />
      </main>
    </>
  );
}
