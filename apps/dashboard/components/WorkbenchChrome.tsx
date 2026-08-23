'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { API_BASE } from '@/lib/config';
import { useLanguage } from '@/lib/i18n';

type Capability = { state?: string; capability_id?: string; name?: string };

const coreLinks = [
  { href: '/overview', zh: '每日简报', en: 'Daily Brief' },
  { href: '/markets', zh: '市场观察', en: 'Markets' },
  { href: '/equities', zh: '股票观察', en: 'Equities', aliases: ['/us-equities'] },
  { href: '/strategies', zh: '策略中心', en: 'Strategies' },
  { href: '/execution', zh: '执行台', en: 'Execution' },
  { href: '/risk-ops', zh: '风险运营', en: 'Risk Ops' },
];

export function WorkbenchPageHeader({
  eyebrow,
  title,
  description,
  tier = 'core',
}: {
  eyebrow: { zh: string; en: string };
  title: { zh: string; en: string };
  description: { zh: string; en: string };
  tier?: 'core' | 'lab' | 'archive';
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  return (
    <header className="workbench-page-header">
      <div>
        <div className="eyebrow">{zh ? eyebrow.zh : eyebrow.en}</div>
        <h1>{zh ? title.zh : title.en}</h1>
        <p>{zh ? description.zh : description.en}</p>
      </div>
      <span className={`tier-badge tier-${tier}`}>
        {tier === 'core' ? (zh ? '核心路径' : 'CORE') : tier === 'lab' ? (zh ? '实验区' : 'LAB') : (zh ? '归档' : 'ARCHIVE')}
      </span>
    </header>
  );
}

export function WorkbenchStatusStrip() {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const pathname = usePathname();
  const query = useQuery<{ rows?: Capability[] }>({
    queryKey: ['workbench-capabilities'],
    queryFn: async ({ signal }) => {
      const response = await fetch(`${API_BASE}/api/capabilities`, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    staleTime: 20_000,
    refetchInterval: 30_000,
  });
  const rows = Array.isArray(query.data?.rows) ? query.data.rows : [];
  const unknown = query.isError || !query.data;
  const lab = rows.find((row) => row.capability_id === 'paper_execution');
  const tone = unknown ? 'unknown' : lab?.state === 'blocked' ? 'blocked' : 'available';
  return (
    <div className="workbench-status-strip" aria-label={zh ? '工作台运行状态' : 'Workbench runtime status'}>
      <span className="status-context">{pathname === '/overview' ? (zh ? '今日工作面' : 'TODAY') : (zh ? '当前工作面' : 'WORKSPACE')}</span>
      <StatusItem label={zh ? '能力矩阵' : 'Capabilities'} value={unknown ? 'UNKNOWN' : (zh ? '已同步' : 'SYNCED')} tone={tone} />
      <StatusItem label={zh ? 'Paper' : 'Paper'} value={unknown ? 'UNKNOWN' : lab?.state?.toUpperCase() || 'UNKNOWN'} tone={lab?.state === 'blocked' ? 'blocked' : unknown ? 'unknown' : 'neutral'} />
      <StatusItem label={zh ? '证据门禁' : 'Evidence gate'} value={zh ? '需核验' : 'VERIFY'} tone="neutral" />
      <Link href="/settings" className="status-settings">{zh ? '运行边界 →' : 'Runtime boundaries →'}</Link>
    </div>
  );
}

function StatusItem({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <span className={`status-item status-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

export function CoreNavigation() {
  const pathname = usePathname();
  const { language } = useLanguage();
  return (
    <div className="core-navigation" role="list" aria-label={language === 'zh' ? '核心工作区' : 'Core workspaces'}>
      {coreLinks.map((item) => {
        const active = pathname === item.href
          || pathname.startsWith(`${item.href}/`)
          || item.aliases?.some((alias) => pathname === alias || pathname.startsWith(`${alias}/`));
        return (
          <Link key={item.href} href={item.href} role="listitem" aria-current={active ? 'page' : undefined} className={active ? 'active' : undefined}>
            {language === 'zh' ? item.zh : item.en}
          </Link>
        );
      })}
    </div>
  );
}
