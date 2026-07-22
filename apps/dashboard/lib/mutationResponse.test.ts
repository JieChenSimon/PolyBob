import { describe, expect, it } from 'vitest';

import { requireSuccessfulMutation } from './mutationResponse';

describe('requireSuccessfulMutation', () => {
  it('returns successful responses', async () => {
    const response = new Response(null, { status: 204 });

    await expect(requireSuccessfulMutation(Promise.resolve(response))).resolves.toBe(response);
  });

  it('rejects non-success responses before callers refetch', async () => {
    await expect(requireSuccessfulMutation(Promise.resolve(
      new Response(null, { status: 409 }),
    ))).rejects.toThrow('HTTP 409');
  });
});
