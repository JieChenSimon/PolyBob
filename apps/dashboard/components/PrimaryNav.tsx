'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLanguage } from '@/lib/i18n';

// Order: overview first, then market surfaces, then execution/strategy/risk,
// settings last. Heavy chart routes keep prefetch disabled (perf contract).
const navItems = [
  { href: '/overview', label: { en: 'Daily Brief', zh: '每日简报' } },
  // Second, right after the brief: the journal is where the north star is
  // actually measured. It sat nowhere at all while the workbench reported
  // research win rates it had no way to confirm.
  { href: '/journal', label: { en: 'Journal', zh: '交易日志' } },
  { href: '/markets', label: { en: 'Markets', zh: '市场观察' }, prefetch: false },
  { href: '/polymarket', label: { en: 'Polymarket', zh: 'Polymarket' }, aliases: ['/btc-5m'] },
  { href: '/crypto', label: { en: 'Crypto', zh: '加密货币' } },
  { href: '/us-equities', label: { en: 'Equities', zh: '股票观察' }, prefetch: false },
  { href: '/tasks', label: { en: 'Tasks', zh: '任务' } },
  // 执行台 / 模拟盘 / 风险运营 / 策略中心 moved to attic/ — they were four tabs
  // of operating surface for zero tradable edges. The shape of a page is a
  // promise, and blanking its numbers does not withdraw it. The scoreboard and
  // the reasons each edge was demoted now live on /overview, which is where a
  // person actually starts.
  { href: '/settings', label: { en: 'Settings', zh: '设置' } },
];

export default function PrimaryNav() {
  const pathname = usePathname();
  const { language, setLanguage } = useLanguage();

  return (
    <nav
      aria-label={language === 'zh' ? '主导航' : 'Primary navigation'}
      className="sticky top-0 z-30 border-b border-stone-200 bg-white/95 backdrop-blur"
    >
      <div className="mx-auto flex w-full max-w-shell flex-wrap items-center gap-x-6 gap-y-1 px-5 md:px-8">
        <Link
          href="/overview"
          aria-label={language === 'zh' ? 'PolyBob 首页' : 'PolyBob home'}
          className="flex shrink-0 items-baseline gap-2 rounded py-3"
        >
          <span className="text-base font-bold tracking-[-0.02em] text-stone-900">PolyBob</span>
          <span className="hidden text-xs text-stone-400 sm:inline">
            {language === 'zh' ? '个人市场工作台' : 'Market Workbench'}
          </span>
        </Link>

        <div
          role="list"
          className="order-3 -mx-5 flex w-[calc(100%+40px)] min-w-0 gap-1 overflow-x-auto px-5 md:order-2 md:mx-0 md:w-auto md:flex-1 md:px-0"
        >
          {navItems.map((item) => {
            const active = pathname === item.href
              || pathname.startsWith(`${item.href}/`)
              || item.aliases?.some((alias) => pathname === alias || pathname.startsWith(`${alias}/`));
            return (
              <Link
                key={item.href}
                href={item.href}
                prefetch={item.prefetch}
                role="listitem"
                aria-current={active ? 'page' : undefined}
                className={`shrink-0 whitespace-nowrap border-b-2 px-2.5 py-3 text-sm transition ${
                  active
                    ? 'border-sky-600 font-semibold text-sky-700'
                    : 'border-transparent font-medium text-stone-500 hover:border-stone-300 hover:text-stone-900'
                }`}
              >
                {item.label[language]}
              </Link>
            );
          })}
        </div>

        <button
          type="button"
          onClick={() => setLanguage(language === 'zh' ? 'en' : 'zh')}
          aria-label={language === 'zh' ? '切换到英文界面' : 'Switch to Chinese interface'}
          className="order-2 ml-auto shrink-0 rounded-md border border-stone-200 px-2.5 py-1 text-xs font-semibold text-stone-600 transition hover:border-sky-500 hover:text-sky-700 md:order-3"
        >
          {language === 'zh' ? 'EN' : '中文'}
        </button>
      </div>
    </nav>
  );
}
