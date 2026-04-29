import RiskOpsOverview from '@/components/RiskOpsOverview';
import SectionIntro from '@/components/SectionIntro';

export default function RiskOpsPage() {
  return (
    <>
      <SectionIntro
        eyebrow="Risk & Ops"
        title="Risk And Operations"
        description="这里先建立风险和系统运营的独立页面，为后续的组合风控、告警、日志和服务健康留出位置。"
      />

      <main className="mx-auto mt-6 w-full max-w-[1380px] px-5 pb-10 md:mt-8 md:px-8">
        <RiskOpsOverview />
      </main>
    </>
  );
}
