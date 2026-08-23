import { Suspense } from 'react';
import BestOpportunity from '@/components/BestOpportunity';
import AltcoinDiscoveryWorkspace from '@/components/AltcoinDiscoveryWorkspace';
import ForecastBatchScanner from '@/components/ForecastBatchScanner';
import { WorkbenchPageHeader } from '@/components/WorkbenchChrome';

export default function AltcoinDiscoveryPage() {
  return (
    <>
      <WorkbenchPageHeader eyebrow={{ zh: '核心工作区', en: 'Core Workspace' }} title={{ zh: '加密货币', en: 'Crypto' }} description={{ zh: '查看加密资产发现、行情、研究预测和单标的详情；实验能力不会自动获得执行权限。', en: 'Review crypto discovery, market data, research forecasts and instrument detail; lab capabilities never inherit execution permission.' }} />
      <div className="mx-auto w-full max-w-shell px-5 pt-6 md:px-8">
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
      <div className="mx-auto w-full max-w-shell px-5 pb-10 md:px-8">
        <ForecastBatchScanner domain="crypto_spot" symbols={['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'DOGE-USDT']} />
      </div>
    </>
  );
}
