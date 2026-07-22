import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const source = readFileSync(new URL('./page.tsx', import.meta.url), 'utf8');

describe('Polymarket route performance contract', () => {
  it('renders a static shell without blocking on workbench data', () => {
    expect(source).not.toContain("export const dynamic = 'force-dynamic'");
    expect(source).not.toContain('async function PolymarketPage');
    expect(source).not.toContain('fetchInitialWorkbench');
    expect(source).not.toMatch(/await\s+fetch\(/);
  });
});
