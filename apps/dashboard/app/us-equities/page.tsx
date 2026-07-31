import USEquityAdvisor from '@/components/USEquityAdvisor';
import WisdomSignalPanel from '@/components/WisdomSignalPanel';
import SectionIntro from '@/components/SectionIntro';

export default function USEquitiesPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '真实行情', en: 'Real Quotes' }}
        title={{ zh: '股票观察', en: 'Equity Monitor' }}
        description={{
          zh: '美股与 A 股的真实报价、走势图、均线和技术加减仓观察；未接入真实组合时只给观察价，不给仓位建议。',
          en: 'US and China equity quotes, charts, moving averages, and technical add/trim watch levels without portfolio sizing.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:px-8">
        <USEquityAdvisor />
        <WisdomSignalPanel symbol="NVDA" domain="us_equity" />
      </main>
    </>
  );
}
