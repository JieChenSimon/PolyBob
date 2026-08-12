import SectionIntro from '@/components/SectionIntro';
import TaskBoard from '@/components/TaskBoard';

export default function TasksPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: 'Git 状态', en: 'Git State' }}
        title={{ zh: '任务看板', en: 'Task Board' }}
        description={{
          zh: '一个事实源：任务、依赖、验收、阻塞与关联提交。',
          en: 'One source of truth for tasks, dependencies, checks, blockers, and commits.',
        }}
      />
      <main className="mx-auto mt-6 w-full max-w-shell px-5 pb-10 md:mt-8 md:px-8">
        <TaskBoard />
      </main>
    </>
  );
}
