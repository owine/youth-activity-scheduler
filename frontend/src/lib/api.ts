export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`API error ${status}`);
  }
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
