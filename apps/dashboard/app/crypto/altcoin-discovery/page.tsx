import { Suspense } from 'react';
import BestOpportunity from '@/components/BestOpportunity';
import AltcoinDiscoveryWorkspace from '@/components/AltcoinDiscoveryWorkspace';
import ForecastBatchScanner from '@/components/ForecastBatchScanner';
import AssetTerminalFrame from '@/components/AssetTerminalFrame';

export default function AltcoinDiscoveryPage() {
  return (
    <>
      <main className="asset-terminal-page">
      <Suspense fallback={<div className="terminal-loading" />}>
      <AssetTerminalFrame asset="CRYPTO SPOT" title="Crypto Market" subtitle="Discovery, spot context and research forecasts stay separate from execution permissions." symbol="BTC-USDT" source="Crypto discovery providers" links={[{ href: '/crypto/altcoin-discovery?symbol=BTC-USDT', label: 'BTC-USDT', meta: 'Bitcoin spot' }, { href: '/crypto/altcoin-discovery?symbol=ETH-USDT', label: 'ETH-USDT', meta: 'Ethereum spot' }, { href: '/crypto/altcoin-discovery?symbol=SOL-USDT', label: 'SOL-USDT', meta: 'Solana spot' }]}>
      <div className="space-y-5">
      <div className="mx-auto w-full px-1">
        {/* The crowding edge fires on eight majors; discovery below scans a much
            wider, unvalidated universe. Leading with the validated one keeps the
            page honest about which part has evidence behind it. */}
        <Suspense fallback={<div className="mb-6 h-28 rounded-xl border-l-4 border-stone-200 bg-stone-50" />}>
          <BestOpportunity
            domain="altcoin"
            title={{ zh: '山寨币今天该看哪一个', en: 'Which coin to look at today' }}
          />
        </Suspense>
      </div>
      <AltcoinDiscoveryWorkspace />
      <div className="mx-auto w-full px-1 pb-2">
        <ForecastBatchScanner domain="crypto_spot" symbols={['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'DOGE-USDT']} />
      </div>
      </div>
      </AssetTerminalFrame>
      </Suspense>
      </main>
    </>
  );
}
