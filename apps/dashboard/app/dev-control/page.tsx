import SectionIntro from '@/components/SectionIntro';
import DevControlBoard from '@/components/DevControlBoard';

export default function DevControlPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '开发控制', en: 'Development Control' }}
        title={{ zh: '开发控制台', en: 'Development Control' }}
        description={{
          zh: '一个事实源：任务、依赖、验收、阻塞与关联提交。',
          en: 'One source of truth for tasks, dependencies, checks, blockers, and commits.',
        }}
      />
      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <DevControlBoard />
      </main>
    </>
  );
}
