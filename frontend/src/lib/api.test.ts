import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { ApiError, api, apiErrorDetail } from './api';

describe('apiErrorDetail', () => {
  it('returns a string detail as-is', () => {
    expect(apiErrorDetail(new ApiError(404, { detail: 'kid 9 not found' }))).toBe(
      'kid 9 not found',
    );
  });

  it('flattens a FastAPI validation list instead of returning objects', () => {
    // Rendering this array as a message crashed React (<ErrorBanner>).
    const body = {
      detail: [
        {
          loc: ['body', 'quiet_hours_end'],
          msg: 'Value error, must be HH:MM',
          type: 'value_error',
        },
        { loc: ['body'], msg: 'Field required', type: 'missing' },
      ],
    };
    expect(apiErrorDetail(new ApiError(422, body))).toBe(
      'quiet_hours_end: Value error, must be HH:MM; Field required',
    );
  });

  it('returns null for non-API errors and bodies without detail', () => {
    expect(apiErrorDetail(new Error('network'))).toBeNull();
    expect(apiErrorDetail(new ApiError(500, 'Internal Server Error'))).toBeNull();
    expect(apiErrorDetail(new ApiError(500, null))).toBeNull();
  });
});

describe('api error bodies', () => {
  it('turns a plain-text 500 into an ApiError carrying the text', async () => {
    server.use(
      http.get('/api/boom', () =>
        HttpResponse.text('Internal Server Error', {
          status: 500,
          headers: { 'content-type': 'text/plain' },
        }),
      ),
    );
    const err: unknown = await api.get('/api/boom').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).body).toBe('Internal Server Error');
  });

  it('parses a JSON error body', async () => {
    server.use(
      http.get('/api/missing', () =>
        HttpResponse.json({ detail: 'kid 9 not found' }, { status: 404 }),
      ),
    );
    const err: unknown = await api.get('/api/missing').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(apiErrorDetail(err)).toBe('kid 9 not found');
  });
});
