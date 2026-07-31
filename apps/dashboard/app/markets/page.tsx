import GlobalSentimentPanel from '@/components/GlobalSentimentPanel';
import VerdictBanner from '@/components/VerdictBanner';
import WisdomSignalPanel from '@/components/WisdomSignalPanel';
import MarketNewsTerminal from '@/components/MarketNewsTerminal';
import MarketsWorkspace from '@/components/MarketsWorkspace';
import SectionIntro from '@/components/SectionIntro';

export default function MarketsPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '核心路径', en: 'Core Path' }}
        title={{ zh: '市场观察', en: 'Markets' }}
        description={{
          zh: '实时市场消息与跨资产影响分析；watchlist、盘口特征、信号和异常。',
          en: 'Real-time market wire with cross-asset impact analysis, plus watchlists, order-book features, and signals.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <VerdictBanner symbol="600519" domain="a_share" />
        <GlobalSentimentPanel />
        <MarketNewsTerminal />
        <MarketsWorkspace />
        <WisdomSignalPanel symbol="600519" domain="a_share" />
      </main>
    </>
  );
}
