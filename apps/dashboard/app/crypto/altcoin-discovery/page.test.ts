import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const source = readFileSync(new URL('./page.tsx', import.meta.url), 'utf8');

describe('Altcoin Discovery route performance contract', () => {
  it('renders a static shell without serializing discovery data', () => {
    expect(source).not.toContain("export const dynamic = 'force-dynamic'");
    expect(source).not.toContain('async function AltcoinDiscoveryPage');
    expect(source).not.toContain('fetchInitialDiscovery');
    expect(source).not.toMatch(/await\s+fetch\(/);
  });
});
