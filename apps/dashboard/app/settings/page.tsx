import SectionIntro from '@/components/SectionIntro';
import SettingsOverview from '@/components/SettingsOverview';

export default function SettingsPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '运行边界', en: 'Runtime Bounds' }}
        title={{ zh: '设置', en: 'Settings' }}
        description={{
          zh: '直接读取后端能力矩阵；明确哪些可用、降级、未知、阻塞或仅供实验。',
          en: 'Live backend truth for available, degraded, unknown, blocked, and experimental capabilities.',
        }}
      />

      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <SettingsOverview />
      </main>
    </>
  );
}
