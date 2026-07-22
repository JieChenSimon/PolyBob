import { describe, expect, it } from 'vitest';

import { createWorkbenchQueryClient, workbenchQueryDefaults } from './queryClient';

describe('workbench query runtime', () => {
  it('uses bounded retries and foreground-only polling defaults', () => {
    expect(workbenchQueryDefaults.queries?.retry).toBe(1);
    expect(workbenchQueryDefaults.queries?.refetchIntervalInBackground).toBe(false);
    expect(workbenchQueryDefaults.queries?.gcTime).toBeGreaterThanOrEqual(5 * 60_000);
  });

  it('creates isolated clients with the workbench defaults', () => {
    const first = createWorkbenchQueryClient();
    const second = createWorkbenchQueryClient();

    expect(first).not.toBe(second);
    expect(first.getDefaultOptions().queries?.retry).toBe(1);
    expect(first.getDefaultOptions().queries?.refetchIntervalInBackground).toBe(false);
  });
});
