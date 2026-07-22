import SectionIntro from '@/components/SectionIntro';
import SettingsOverview from '@/components/SettingsOverview';

export default function SettingsPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '运行边界', en: 'Runtime Bounds' }}
        title={{ zh: '设置', en: 'Settings' }}
        description={{
          zh: '记录核心路径、数据源、lab 边界和策略配置入口。',
          en: 'Core path, data sources, lab boundaries, and strategy configuration entry points.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <SettingsOverview />
      </main>
    </>
  );
}
