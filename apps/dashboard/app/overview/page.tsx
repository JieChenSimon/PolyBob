import BacktestResults from '@/components/BacktestResults';
import OverviewSummary from '@/components/OverviewSummary';
import PersonalBrief from '@/components/PersonalBrief';
import SectionIntro from '@/components/SectionIntro';

export default function OverviewPage() {
  return (
    <>
      <SectionIntro
        eyebrow="Personal Desk"
        title="Daily Brief"
        description="这是个人研究交易工作台的入口：优先回答今天该看什么、哪些信号需要复核、风险有没有异常。实验功能不会默认占用首页判断流。"
      />

      <main className="mx-auto mt-6 w-full max-w-[1380px] px-5 pb-10 md:mt-8 md:px-8">
        <PersonalBrief />

        <div className="mt-6">
          <OverviewSummary />
        </div>

        <div className="mt-6">
          <BacktestResults />
        </div>
      </main>
    </>
  );
}
