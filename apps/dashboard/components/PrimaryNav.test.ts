import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const source = readFileSync(new URL('./PrimaryNav.tsx', import.meta.url), 'utf8');

describe('PrimaryNav prefetch contract', () => {
  it('disables automatic prefetch only for heavy chart routes', () => {
    expect(source).toMatch(/href:\s*'\/markets'.*prefetch:\s*false/);
    expect(source).toMatch(/href:\s*'\/us-equities'.*prefetch:\s*false/);
    expect(source.match(/prefetch:\s*false/g)).toHaveLength(2);
    expect(source).toContain('prefetch={item.prefetch}');
  });
});
