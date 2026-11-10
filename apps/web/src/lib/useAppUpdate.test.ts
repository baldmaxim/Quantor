import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAppUpdate } from '@/lib/useAppUpdate';

const BUILT = 'sha-built';

const answer = (version: string | null) =>
  Promise.resolve(new Response(JSON.stringify({ version }), { status: 200 }));

const advance = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe('useAppUpdate', () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('NEXT_PUBLIC_BUILD_VERSION', BUILT);
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('совпадающая версия: тост не виден', async () => {
    fetchMock.mockImplementation(() => answer(BUILT));
    const { result } = renderHook(() => useAppUpdate());

    await advance(60_000);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.visible).toBe(false);
  });

  it('другая версия: тост виден', async () => {
    fetchMock.mockImplementation(() => answer('sha-new'));
    const { result } = renderHook(() => useAppUpdate());

    expect(result.current.visible).toBe(false);
    await advance(60_000);

    expect(result.current.visible).toBe(true);
  });

  it('«Позже» скрывает тост, более новая версия показывает снова', async () => {
    fetchMock.mockImplementation(() => answer('sha-new'));
    const { result } = renderHook(() => useAppUpdate());
    await advance(60_000);
    expect(result.current.visible).toBe(true);

    act(() => result.current.dismiss());
    expect(result.current.visible).toBe(false);

    // Та же версия при следующей проверке тост не возвращает.
    await advance(5 * 60_000);
    expect(result.current.visible).toBe(false);

    fetchMock.mockImplementation(() => answer('sha-newer'));
    await advance(5 * 60_000);
    expect(result.current.visible).toBe(true);
  });

  it('ошибка сети: тост не виден', async () => {
    fetchMock.mockImplementation(() => Promise.reject(new TypeError('network')));
    const { result } = renderHook(() => useAppUpdate());

    await advance(60_000);

    expect(fetchMock).toHaveBeenCalled();
    expect(result.current.visible).toBe(false);
  });

  it('не production или версия не задана: проверок нет', async () => {
    fetchMock.mockImplementation(() => answer('sha-new'));

    vi.stubEnv('NEXT_PUBLIC_BUILD_VERSION', '');
    const noVersion = renderHook(() => useAppUpdate());
    await advance(60_000);
    expect(noVersion.result.current.visible).toBe(false);

    vi.stubEnv('NEXT_PUBLIC_BUILD_VERSION', BUILT);
    vi.stubEnv('NODE_ENV', 'development');
    const dev = renderHook(() => useAppUpdate());
    await advance(60_000);
    expect(dev.result.current.visible).toBe(false);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('возвращение на вкладку проверяет не чаще раза в минуту', async () => {
    fetchMock.mockImplementation(() => answer(BUILT));
    renderHook(() => useAppUpdate());
    await advance(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await advance(30_000);
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await advance(30_000);
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('после размонтирования таймеры сняты', async () => {
    fetchMock.mockImplementation(() => answer(BUILT));
    const { unmount } = renderHook(() => useAppUpdate());

    unmount();
    await advance(10 * 60_000);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('«Обновить» без waiting worker перезагружает страницу', () => {
    fetchMock.mockImplementation(() => answer(BUILT));
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    const { result } = renderHook(() => useAppUpdate());

    act(() => result.current.apply());

    expect(reload).toHaveBeenCalledTimes(1);
  });
});
