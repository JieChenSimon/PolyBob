/**
 * Reject a failed mutation *with the server's reason attached*.
 *
 * The API refuses things on purpose — the promotion gate turns away strategies
 * that never cleared PromotionGate on real history, and says exactly which one
 * and why in FastAPI's `detail`. Throwing a bare `HTTP 403` would strip that
 * down to a number, and a safety gate that cannot explain itself is one you
 * switch off in frustration. So the reason travels with the error.
 *
 * Reading the body is best-effort: a refusal must still surface as a refusal
 * even when the response has no body, isn't JSON, or has already been consumed.
 */
export async function requireSuccessfulMutation(
  request: Promise<Response>,
): Promise<Response> {
  const response = await request;
  if (!response.ok) {
    const reason = await failureReason(response);
    throw new Error(reason ? `HTTP ${response.status}: ${reason}` : `HTTP ${response.status}`);
  }
  return response;
}

/** FastAPI's `detail`, a plain-text body, or nothing — never a thrown error. */
async function failureReason(response: Response): Promise<string | null> {
  let body: string;
  try {
    body = await response.clone().text();
  } catch {
    return null;
  }
  const trimmed = body.trim();
  if (!trimmed) {
    return null;
  }
  try {
    const detail = (JSON.parse(trimmed) as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail.trim();
    }
    // Validation errors arrive as a list of objects; JSON is more useful than
    // "[object Object]", but an unbounded blob in a toast is not.
    return detail === undefined ? null : truncate(JSON.stringify(detail));
  } catch {
    return truncate(trimmed);
  }
}

function truncate(text: string, limit = 300): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}
