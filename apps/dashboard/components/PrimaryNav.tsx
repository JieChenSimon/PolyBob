'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLanguage } from '@/lib/i18n';

// The primary rail is deliberately compact; specialized Lab/Archive routes
// remain reachable by deep link and from Settings without competing with the
// operator's daily workflow.
const navItems = [
  { href: '/overview', label: { en: 'Daily Brief', zh: '每日简报' } },
  { href: '/markets', label: { en: 'Prediction Markets', zh: '预测市场' }, prefetch: false },
  { href: '/us-equities', label: { en: 'US Equities', zh: '美股' }, prefetch: false, aliases: ['/equities'] },
  { href: '/a-shares', label: { en: 'A-Shares', zh: 'A股' }, prefetch: false },
  { href: '/crypto/altcoin-discovery', label: { en: 'Crypto', zh: '加密货币' }, prefetch: false, aliases: ['/crypto'] },
  { href: '/btc-5m', label: { en: 'BTC 5m', zh: 'BTC 5分钟' }, prefetch: false, aliases: ['/polymarket'] },
  { href: '/strategies', label: { en: 'Strategies', zh: '策略中心' } },
  { href: '/execution', label: { en: 'Execution', zh: '执行台' } },
  { href: '/risk-ops', label: { en: 'Risk Ops', zh: '风险运营' } },
  { href: '/settings', label: { en: 'Settings', zh: '设置' } },
];

export default function PrimaryNav() {
  const pathname = usePathname();
  const { language, setLanguage } = useLanguage();
  const terminalRoute = ['/us-equities', '/a-shares', '/crypto', '/btc-5m', '/polymarket'].some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );

  return (
    <nav
      aria-label={language === 'zh' ? '主导航' : 'Primary navigation'}
      className={`sticky top-0 z-30 border-b backdrop-blur ${terminalRoute ? 'terminal-app-nav border-slate-800 bg-slate-950/95' : 'border-stone-200 bg-white/95'}`}
    >
      <div className="mx-auto flex w-full max-w-shell flex-wrap items-center gap-x-6 gap-y-1 px-5 md:px-8">
        <Link
          href="/overview"
          aria-label={language === 'zh' ? 'PolyBob 首页' : 'PolyBob home'}
          className="flex shrink-0 items-baseline gap-2 rounded py-3"
        >
          <span className={`text-base font-bold tracking-[-0.02em] ${terminalRoute ? 'text-slate-100' : 'text-stone-900'}`}>PolyBob</span>
          <span className={`hidden text-xs sm:inline ${terminalRoute ? 'text-slate-500' : 'text-stone-400'}`}>
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
                aria-current={active ? 'page' : undefined}
                className={`shrink-0 whitespace-nowrap border-b-2 px-2.5 py-3 text-sm transition ${
                  active
                    ? terminalRoute ? 'border-sky-400 font-semibold text-sky-300' : 'border-sky-600 font-semibold text-sky-700'
                    : terminalRoute ? 'border-transparent font-medium text-slate-400 hover:border-slate-600 hover:text-slate-100' : 'border-transparent font-medium text-stone-500 hover:border-stone-300 hover:text-stone-900'
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
          className={`order-2 ml-auto shrink-0 rounded-md border px-2.5 py-1 text-xs font-semibold transition md:order-3 ${terminalRoute ? 'border-slate-700 text-slate-300 hover:border-sky-400 hover:text-sky-300' : 'border-stone-200 text-stone-600 hover:border-sky-500 hover:text-sky-700'}`}
        >
          {language === 'zh' ? 'EN' : '中文'}
        </button>
      </div>
    </nav>
  );
}
