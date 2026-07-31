import { describe, expect, it } from 'vitest';

import { requireSuccessfulMutation } from './mutationResponse';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

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

  it("carries the server's reason so a refusal explains itself", async () => {
    // The promotion gate's actual refusal: without the detail this reads as a
    // bare 403 and looks like a bug rather than the gate doing its job.
    await expect(requireSuccessfulMutation(Promise.resolve(
      jsonResponse(403, { detail: "策略 'spread_arbitrage_v1' 未过晋级门禁，留 lab" }),
    ))).rejects.toThrow("HTTP 403: 策略 'spread_arbitrage_v1' 未过晋级门禁，留 lab");
  });

  it('falls back to the raw body when the error is not FastAPI-shaped', async () => {
    await expect(requireSuccessfulMutation(Promise.resolve(
      new Response('upstream timed out', { status: 502 }),
    ))).rejects.toThrow('HTTP 502: upstream timed out');
  });

  it('serialises structured validation details instead of [object Object]', async () => {
    await expect(requireSuccessfulMutation(Promise.resolve(
      jsonResponse(422, { detail: [{ loc: ['body', 'legs'], msg: 'field required' }] }),
    ))).rejects.toThrow(/field required/);
  });

  it('truncates a runaway body rather than filling the UI with it', async () => {
    const error = await requireSuccessfulMutation(Promise.resolve(
      new Response('x'.repeat(5000), { status: 500 }),
    )).catch((e: Error) => e);

    expect((error as Error).message.length).toBeLessThan(400);
    expect((error as Error).message).toMatch(/…$/);
  });

  it('still rejects when the body is empty or unreadable', async () => {
    await expect(requireSuccessfulMutation(Promise.resolve(
      new Response('   ', { status: 500 }),
    ))).rejects.toThrow('HTTP 500');
  });

  it('leaves the original body readable for callers that need it', async () => {
    // Cloning matters: consuming the stream here would break any caller that
    // reads the response itself.
    const response = jsonResponse(400, { detail: 'nope' });
    await requireSuccessfulMutation(Promise.resolve(response)).catch(() => undefined);

    await expect(response.json()).resolves.toEqual({ detail: 'nope' });
  });
});
