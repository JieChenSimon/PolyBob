import ExecutionWorkspace from '@/components/ExecutionWorkspace';
import SectionIntro from '@/components/SectionIntro';

export default function ExecutionPage() {
  return (
    <>
      <SectionIntro
        eyebrow="Execution Desk"
        title="Execution"
        description="执行页承接 intent、风控、basket 和 paper 记录。BTC demo auto trader 属于 lab，默认不进入核心启动路径。"
      />

      <main className="mx-auto mt-6 w-full max-w-[1380px] px-5 pb-10 md:mt-8 md:px-8">
        <ExecutionWorkspace />
      </main>
    </>
  );
}
