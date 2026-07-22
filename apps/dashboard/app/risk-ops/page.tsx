import RiskOpsOverview from '@/components/RiskOpsOverview';
import SectionIntro from '@/components/SectionIntro';

export default function RiskOpsPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '核心路径', en: 'Core Path' }}
        title={{ zh: '风险运营', en: 'Risk Ops' }}
        description={{
          zh: '查看组合风险、链上告警、服务健康和运行备注。',
          en: 'Portfolio risk, onchain alerts, service health, and operating notes.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <RiskOpsOverview />
      </main>
    </>
  );
}
