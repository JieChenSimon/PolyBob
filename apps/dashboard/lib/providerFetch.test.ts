import { afterEach, describe, expect, it, vi } from 'vitest';

import { providerFetch } from './providerFetch';

afterEach(() => {
  vi.unstubAllGlobals();
});

function pendingFetch(_input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return new Promise((_resolve, reject) => {
    const signal = init?.signal;
    if (!signal) {
      reject(new Error('missing abort signal'));
      return;
    }

    const rejectOnAbort = () => reject(signal.reason);
    if (signal.aborted) {
      rejectOnAbort();
      return;
    }
    signal.addEventListener('abort', rejectOnAbort, { once: true });
  });
}

describe('providerFetch', () => {
  it('aborts a provider request after the total timeout', async () => {
    vi.stubGlobal('fetch', pendingFetch);

    await expect(providerFetch('https://provider.test/slow', {}, 10)).rejects.toMatchObject({
      name: 'TimeoutError',
    });
  });

  it('honors caller cancellation before the timeout', async () => {
    vi.stubGlobal('fetch', pendingFetch);
    const controller = new AbortController();
    const callerError = new Error('caller cancelled');

    const request = providerFetch(
      'https://provider.test/cancelled',
      { signal: controller.signal },
      1_000,
    );
    controller.abort(callerError);

    await expect(request).rejects.toBe(callerError);
  });
});
