export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`API error ${status}`);
  }
}

/**
 * The server's error message from an ApiError, or null.
 *
 * FastAPI sends `detail` as a string for HTTPException, but as a list of
 * `{loc, msg, type}` objects for a request-validation 422. Rendering that list
 * as a message crashes React, so it is flattened to "field: msg; …".
 */
export function apiErrorDetail(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const detail = (err.body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      const item = d as { loc?: unknown[]; msg?: unknown };
      const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : undefined;
      const msg = typeof item.msg === 'string' ? item.msg : JSON.stringify(d);
      return field !== undefined && field !== 'body' ? `${String(field)}: ${msg}` : msg;
    });
    return parts.length ? parts.join('; ') : null;
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!r.ok) {
    let body: unknown;
    try {
      body = await r.json();
    } catch {
      body = await r.text();
    }
    throw new ApiError(r.status, body);
  }
  if (r.status === 204 || r.headers.get('content-length') === '0') {
    return undefined as T;
  }
  const text = await r.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const api = {
  get<T>(path: string) {
    return request<T>(path);
  },
  post<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  patch<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  },
  delete<T = void>(path: string) {
    return request<T>(path, { method: 'DELETE' });
  },
};
