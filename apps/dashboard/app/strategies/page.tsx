import SectionIntro from '@/components/SectionIntro';
import StrategyCatalog from '@/components/StrategyCatalog';

export default function StrategiesPage() {
  return (
    <>
      <SectionIntro
        eyebrow="Strategy Center"
        title="Strategies"
        description="第一阶段先把策略目录、参数模板和风险基线从代码里抬出来，形成统一的策略中心入口。"
      />

      <main className="mx-auto mt-6 w-full max-w-[1380px] px-5 pb-10 md:mt-8 md:px-8">
        <StrategyCatalog />
      </main>
    </>
  );
}
