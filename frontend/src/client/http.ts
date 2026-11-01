/** Platform-neutral authenticated HTTP dispatch. The host owns credential storage. */
export interface ServiceSession {
  baseUrl: string;
  signal: AbortSignal;
  token: () => Promise<string | undefined>;
  renew: (rejectedToken: string | undefined) => Promise<string | undefined>;
  assertCurrent: () => void;
  language?: string;
  observeSecrets?: (headers: Headers, body: BodyInit | null | undefined) => void;
}

export function requireServiceUrl(input: string, baseUrl: string): void {
  const url = new URL(input, `${baseUrl}/`);
  const base = new URL(baseUrl);
  if (url.origin !== base.origin || url.username || url.password || url.hash) {
    throw new Error('Authenticated requests must stay on the active center');
  }
}

export function isSessionRejection(status: number | undefined, data: unknown): boolean {
  return status === 401 && typeof data === 'object' && data !== null
    && 'error_code' in data && data.error_code === 'client_auth_required';
}

export function isReadRequest(method: string): boolean {
  return ['GET', 'HEAD'].includes(method.toUpperCase());
}

export async function fetchService(
  session: ServiceSession, input: RequestInfo | URL, init: RequestInit = {},
): Promise<Response> {
  requireServiceUrl(input instanceof Request ? input.url : String(input), session.baseUrl);
  session.assertCurrent();
  const token = await session.token();
  session.assertCurrent();
  const headers = new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined));
  headers.delete('X-Magi-Session-Token');
  if (token) headers.set('X-Magi-Session-Token', token);
  if (session.language) headers.set('Accept-Language', session.language);
  const sourceSignal = init.signal ?? (input instanceof Request ? input.signal : undefined);
  const signal = sourceSignal ? AbortSignal.any([session.signal, sourceSignal]) : session.signal;
  session.observeSecrets?.(headers, init.body);
  let response = await fetch(input, { ...init, headers, signal, redirect: 'error', credentials: 'omit' });
  session.assertCurrent();
  if (response.status === 401) {
    const payload: unknown = await response.clone().json().catch(() => undefined);
    if (isSessionRejection(response.status, payload)) {
      const refreshed = await session.renew(token);
      session.assertCurrent();
      const method = init.method ?? (input instanceof Request ? input.method : 'GET');
      if (refreshed && isReadRequest(method)) {
        await response.body?.cancel();
        headers.set('X-Magi-Session-Token', refreshed);
        session.observeSecrets?.(headers, init.body);
        response = await fetch(input, { ...init, headers, signal, redirect: 'error', credentials: 'omit' });
        session.assertCurrent();
      }
    }
  }
  return response;
}
