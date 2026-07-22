'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useRef } from 'react';

import { appendNavigationMetric, type NavigationMetric } from '@/lib/navigationMetrics';

declare global {
  interface Window {
    __polybobNavigationMetrics?: NavigationMetric[];
  }
}

interface PendingNavigation {
  from: string;
  to: string;
  startedAt: number;
}

export default function NavigationPerformanceMonitor() {
  const pathname = usePathname();
  const pending = useRef<PendingNavigation | null>(null);

  useEffect(() => {
    document.documentElement.dataset.polybobNavigationMonitor = 'ready';
  }, []);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const target = event.target instanceof Element ? event.target.closest('a[href]') : null;
      const href = target?.getAttribute('href');
      if (!href?.startsWith('/') || href === pathname) {
        return;
      }
      pending.current = { from: pathname, to: href, startedAt: Date.now() };
    };

    document.addEventListener('click', handleClick, { capture: true });
    return () => document.removeEventListener('click', handleClick, { capture: true });
  }, [pathname]);

  useEffect(() => {
    const navigation = pending.current;
    if (!navigation || (navigation.to !== pathname && !pathname.startsWith(`${navigation.to}/`))) {
      return;
    }
    pending.current = null;
    const frame = window.requestAnimationFrame(() => {
      const durationMs = Date.now() - navigation.startedAt;
      window.__polybobNavigationMetrics = appendNavigationMetric(
        window.__polybobNavigationMetrics ?? [],
        {
          from: navigation.from,
          to: pathname,
          durationMs,
          recordedAt: Date.now(),
        },
      );
      document.documentElement.dataset.polybobNavigationDuration = String(durationMs);
      document.documentElement.dataset.polybobNavigationFrom = navigation.from;
      document.documentElement.dataset.polybobNavigationTo = pathname;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [pathname]);

  return null;
}
