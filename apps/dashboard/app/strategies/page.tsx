import SectionIntro from '@/components/SectionIntro';
import StrategyCatalog from '@/components/StrategyCatalog';

export default function StrategiesPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '核心路径', en: 'Core Path' }}
        title={{ zh: '策略中心', en: 'Strategies' }}
        description={{
          zh: '统一查看策略模板、参数基线、运行实例和待提交意图。',
          en: 'Review strategy templates, parameter baselines, runtime instances, and pending intents.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <StrategyCatalog />
      </main>
    </>
  );
}
