'use client';

import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';
import ErrorState from '@/components/ui/ErrorState';
import LoadingSkeleton from '@/components/ui/LoadingSkeleton';

type State = 'todo' | 'doing' | 'blocked' | 'done' | 'dropped';
type Task = {
  id: string;
  title: string;
  state: State;
  p: 'P0' | 'P1' | 'P2' | 'P3';
  area: string;
  why: string;
  checks: Array<{ text: string; done: boolean }>;
  deps: string[];
  branch: string | null;
  blocked: string | null;
  updated: string;
  progress: { done: number; total: number };
  commits: Array<{ sha: string; date: string; subject: string }>;
};
type Payload = {
  tasks: Task[];
  counts: Record<State, number>;
  completion_pct: number;
  updated: string;
};

const states: State[] = ['todo', 'doing', 'blocked', 'done'];
const tone: Record<State, string> = {
  todo: 'border-stone-300', doing: 'border-sky-500', blocked: 'border-rose-500',
  done: 'border-emerald-500', dropped: 'border-stone-300 opacity-60',
};

export default function TaskBoard() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const query = useQuery<Payload>({
    queryKey: ['task-board'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/tasks`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    refetchInterval: 10_000,
  });

  if (query.isPending) return <LoadingSkeleton count={5} />;
  if (query.isError || !query.data) {
    return <ErrorState title={zh ? '无法读取任务' : 'Could not load tasks'} message="/api/tasks" />;
  }
  const data = query.data;
  const open = data.tasks.length - data.counts.done - data.counts.dropped;

  return (
    <div>
      <section className="panel mb-4 overflow-hidden">
        <div className="grid gap-px bg-stone-200 sm:grid-cols-4">
          <Metric label={zh ? '完成度' : 'Complete'} value={`${data.completion_pct}%`} />
          <Metric label={zh ? '未完成' : 'Open'} value={String(open)} />
          <Metric label={zh ? '进行中' : 'Doing'} value={`${data.counts.doing}/3`} />
          <Metric label={zh ? '阻塞' : 'Blocked'} value={String(data.counts.blocked)} bad={data.counts.blocked > 0} />
        </div>
        <div className="h-1.5 bg-stone-100" aria-label={`${data.completion_pct}%`}>
          <div className="h-full bg-emerald-500 transition-all" style={{ width: `${data.completion_pct}%` }} />
        </div>
      </section>

      <div className="grid items-start gap-3 lg:grid-cols-4">
        {states.map((state) => {
          const rows = data.tasks.filter((task) => task.state === state);
          return (
            <section key={state} aria-label={state} className="min-w-0">
              <div className="mb-2 flex items-center justify-between px-1">
                <h2 className="text-xs font-bold uppercase tracking-wide text-stone-600">
                  {label(state, zh)}
                </h2>
                <span className="font-mono text-xs text-stone-400">{rows.length}</span>
              </div>
              <div className="space-y-2">
                {rows.map((task) => <TaskCard key={task.id} task={task} zh={zh} />)}
                {rows.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-stone-200 px-3 py-6 text-center text-xs text-stone-400">—</div>
                ) : null}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

function TaskCard({ task, zh }: { task: Task; zh: boolean }) {
  const pct = Math.round(task.progress.done / task.progress.total * 100);
  return (
    <article className={`rounded-lg border border-l-4 bg-white p-3 shadow-[0_1px_2px_rgba(28,25,23,0.04)] ${tone[task.state]}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] font-semibold text-stone-500">{task.id}</span>
        <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${task.p === 'P0' ? 'bg-rose-100 text-rose-700' : task.p === 'P1' ? 'bg-amber-100 text-amber-700' : 'bg-stone-100 text-stone-600'}`}>
          {task.p}
        </span>
      </div>
      <h3 className="mt-1.5 text-sm font-bold leading-5 text-stone-900">{task.title}</h3>
      <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-stone-500">{task.why}</p>
      {task.blocked ? <p className="mt-2 rounded bg-rose-50 px-2 py-1.5 text-[11px] leading-4 text-rose-700">{task.blocked}</p> : null}
      <div className="mt-3 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded bg-stone-100">
          <div className="h-full bg-sky-500" style={{ width: `${pct}%` }} />
        </div>
        <span className="font-mono text-[10px] text-stone-500">{task.progress.done}/{task.progress.total}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 text-[10px] text-stone-400">
        <span>{task.area}</span>
        {task.deps.length ? <span>{zh ? '依赖' : 'deps'} {task.deps.join(', ')}</span> : null}
        {task.commits.length ? <span className="font-mono">git {task.commits[0].sha}</span> : null}
      </div>
    </article>
  );
}

function Metric({ label: text, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return <div className="bg-white px-4 py-3"><div className="text-[10px] uppercase tracking-wide text-stone-500">{text}</div><div className={`mt-0.5 font-mono text-xl font-bold ${bad ? 'text-rose-600' : 'text-stone-900'}`}>{value}</div></div>;
}

function label(state: State, zh: boolean) {
  const labels = zh
    ? { todo: '待办', doing: '进行中', blocked: '阻塞', done: '完成', dropped: '放弃' }
    : { todo: 'Todo', doing: 'Doing', blocked: 'Blocked', done: 'Done', dropped: 'Dropped' };
  return labels[state];
}
