'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const navItems = [
  { href: '/overview', label: 'Overview' },
  { href: '/markets', label: 'Markets' },
  { href: '/strategies', label: 'Strategies' },
  { href: '/execution', label: 'Execution' },
  { href: '/risk-ops', label: 'Risk & Ops' },
  { href: '/settings', label: 'Settings' },
];

export default function PrimaryNav() {
  const pathname = usePathname();

  return (
    <nav className="panel sticky top-5 z-20 mx-auto mt-5 flex w-full max-w-[1380px] items-center justify-between gap-4 px-5 py-4 md:mt-8 md:px-8">
      <div>
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-stone-500">
          PolyBob
        </div>
        <div className="mt-1 text-lg font-bold tracking-[-0.04em] text-stone-900">
          Personal Market Workbench
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        {navItems.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                active
                  ? 'bg-stone-900 text-white shadow-[0_10px_20px_rgba(28,23,20,0.16)]'
                  : 'bg-stone-100 text-stone-600 hover:bg-amber-100 hover:text-stone-900'
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
