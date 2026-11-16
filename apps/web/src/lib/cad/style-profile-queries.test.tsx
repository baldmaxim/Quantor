import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  profile: vi.fn(),
  preview: vi.fn(),
  create: vi.fn(),
  accept: vi.fn(),
}));

vi.mock('@quantor/api-client', () => ({
  getStyleProfile: api.profile,
  getStylePreview: api.preview,
  createStylePreview: api.create,
  createStyleVersionFromPreview: api.accept,
}));

import { STYLE_PREVIEW_POLL_MS, useStylePreviewJob, useStyleProfile } from './style-profile-queries';

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {children}
  </QueryClientProvider>
);

describe('style-profile-queries', () => {
  it('404 - профиля нет: данные null, не ошибка', async () => {
    api.profile.mockRejectedValue({ detail: { code: 'NOT_FOUND' } });
    const { result } = renderHook(() => useStyleProfile('p1', 'd1', true), { wrapper });
    await waitFor(() => expect(result.current.data).toBeNull());
    expect(result.current.isError).toBe(false);
  });

  it('без флага запросов нет', () => {
    api.profile.mockClear();
    renderHook(() => useStyleProfile('p1', 'd1', false), { wrapper });
    expect(api.profile).not.toHaveBeenCalled();
  });

  it('опрос идёт при queued и running и останавливается при завершении', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const read = (status: string) => ({
        data: { job_id: 'j', status, error_code: null, error_message: null, result: null },
      });
      api.preview
        .mockResolvedValueOnce(read('queued'))
        .mockResolvedValueOnce(read('running'))
        .mockResolvedValue(read('succeeded'));
      const { result } = renderHook(() => useStylePreviewJob('p1', 'd1', 'j'), { wrapper });
      await waitFor(() => expect(api.preview).toHaveBeenCalledTimes(1));
      await vi.advanceTimersByTimeAsync(STYLE_PREVIEW_POLL_MS + 50);
      await waitFor(() => expect(api.preview).toHaveBeenCalledTimes(2));
      await vi.advanceTimersByTimeAsync(STYLE_PREVIEW_POLL_MS + 50);
      await waitFor(() => expect(result.current.data?.status).toBe('succeeded'));
      const calls = api.preview.mock.calls.length;
      await vi.advanceTimersByTimeAsync(STYLE_PREVIEW_POLL_MS * 3);
      expect(api.preview).toHaveBeenCalledTimes(calls);
    } finally {
      vi.useRealTimers();
    }
  });
});
