import SimulationWorkspace from '@/components/SimulationWorkspace';
import SectionIntro from '@/components/SectionIntro';

export default function SimulationPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '核心路径', en: 'Core Path' }}
        title={{ zh: '模拟盘', en: 'Simulation' }}
        description={{
          zh: '模拟盘：用真实行情长期检验策略，积累可信的绩效数据。',
          en: 'Simulation: test strategies against live market data over time to build trustworthy performance evidence.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <SimulationWorkspace />
      </main>
    </>
  );
}
