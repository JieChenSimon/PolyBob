export async function requireSuccessfulMutation(
  request: Promise<Response>,
): Promise<Response> {
  const response = await request;
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response;
}
