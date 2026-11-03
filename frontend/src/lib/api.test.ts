import { describe, it, expect } from 'vitest';
import { ApiError, apiErrorDetail } from './api';

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
