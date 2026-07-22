export const providerTimeoutMs = 8_000;

export function providerAbortSignal(
  callerSignal: AbortSignal | null | undefined,
  timeoutMs = providerTimeoutMs,
): AbortSignal {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  return callerSignal
    ? AbortSignal.any([callerSignal, timeoutSignal])
    : timeoutSignal;
}

export function providerFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = providerTimeoutMs,
): Promise<Response> {
  return fetch(input, {
    ...init,
    signal: providerAbortSignal(init.signal, timeoutMs),
  });
}
