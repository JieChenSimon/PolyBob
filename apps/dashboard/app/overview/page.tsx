import OverviewWorkspace from '@/components/OverviewWorkspace';
import SectionIntro from '@/components/SectionIntro';

export default function OverviewPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '核心路径', en: 'Core Path' }}
        title={{ zh: '每日简报', en: 'Daily Brief' }}
        description={{
          zh: '先看今日市场、待复核信号和异常风险；实验模块不占用首页判断流。',
          en: 'Review today’s markets, signals that need confirmation, and abnormal risk first.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <OverviewWorkspace />
      </main>
    </>
  );
}
