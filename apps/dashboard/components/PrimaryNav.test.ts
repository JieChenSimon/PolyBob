import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const source = readFileSync(new URL('./PrimaryNav.tsx', import.meta.url), 'utf8');

describe('PrimaryNav prefetch contract', () => {
  it('disables automatic prefetch only for heavy chart routes', () => {
    expect(source).toMatch(/href:\s*'\/markets'.*prefetch:\s*false/);
    expect(source).toMatch(/href:\s*'\/us-equities'.*prefetch:\s*false/);
    expect(source.match(/prefetch:\s*false/g)).toHaveLength(5);
    expect(source).toContain('prefetch={item.prefetch}');
  });

  it('keeps the primary rail aligned with the professional core workspaces', () => {
    for (const route of ['/overview', '/markets', '/us-equities', '/a-shares', '/crypto/altcoin-discovery', '/btc-5m', '/strategies', '/execution', '/risk-ops', '/settings']) {
      expect(source).toContain(`href: '${route}'`);
    }
    expect(source).not.toContain("href: '/journal'");
    expect(source).not.toContain("href: '/dev-control'");
  });
});
