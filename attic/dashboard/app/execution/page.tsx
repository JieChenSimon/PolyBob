import ExecutionWorkspace from '@/components/ExecutionWorkspace';
import SectionIntro from '@/components/SectionIntro';

export default function ExecutionPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '核心路径', en: 'Core Path' }}
        title={{ zh: '执行台', en: 'Execution' }}
        description={{
          zh: '承接 intent、风控检查、basket 和 paper 记录；lab 自动交易默认关闭。',
          en: 'Intents, risk checks, baskets, and paper records; lab auto trading stays off by default.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <ExecutionWorkspace />
      </main>
    </>
  );
}
