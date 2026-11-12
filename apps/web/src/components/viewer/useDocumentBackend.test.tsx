import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RenderBackend } from '@/lib/viewer/backend';

const opened = vi.hoisted(() => ({
  list: [] as { destroyed: boolean; destroy: () => void }[],
  fail: false,
  calls: 0,
}));

vi.mock('@/lib/viewer/pdfjs-backend', () => ({
  PdfJsRenderBackend: {
    open: async () => {
      opened.calls += 1;
      if (opened.fail) throw Object.assign(new Error('x'), { code: 'PDF_LOAD_FAILED' });
      const backend = {
        destroyed: false,
        destroy() {
          backend.destroyed = true;
        },
      };
      opened.list.push(backend);
      return backend;
    },
  },
}));

import { resetDocumentCacheForTests, useDocumentBackend } from './useDocumentBackend';

beforeEach(() => {
  resetDocumentCacheForTests();
  opened.list = [];
  opened.fail = false;
  opened.calls = 0;
});

const closed = (backend: RenderBackend | null): boolean =>
  (backend as unknown as { destroyed: boolean } | null)?.destroyed === true;

describe('useDocumentBackend', () => {
  it('открывает документ и отдаёт отрисовщик', async () => {
    const { result } = renderHook(({ url }) => useDocumentBackend(url), {
      initialProps: { url: 'u1' as string | null },
    });
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.backend).not.toBeNull());
    expect(result.current.errorCode).toBeNull();
  });

  it('выключили и включили тот же адрес: документ не закрывается и не открывается заново', async () => {
    const { result, rerender } = renderHook(({ url }) => useDocumentBackend(url), {
      initialProps: { url: 'u1' as string | null },
    });
    await waitFor(() => expect(result.current.backend).not.toBeNull());
    const first = result.current.backend;

    rerender({ url: null });
    expect(result.current.backend).toBeNull();
    expect(closed(first)).toBe(false);

    rerender({ url: 'u1' });
    // В первом же кадре после возврата - загрузка, затем тот же живой отрисовщик из кеша.
    expect(result.current.backend).toBeNull();
    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.backend).not.toBeNull());
    expect(result.current.backend).toBe(first);
    expect(closed(result.current.backend)).toBe(false);
    expect(opened.calls).toBe(1);
  });

  it('повторное монтирование с тем же адресом не открывает документ второй раз', async () => {
    const first = renderHook(() => useDocumentBackend('u1'));
    await waitFor(() => expect(first.result.current.backend).not.toBeNull());
    first.unmount();

    const second = renderHook(() => useDocumentBackend('u1'));
    await waitFor(() => expect(second.result.current.backend).not.toBeNull());

    expect(second.result.current.backend).toBe(first.result.current.backend);
    expect(opened.calls).toBe(1);
    expect(opened.list.some((backend) => backend.destroyed)).toBe(false);
  });

  it('третий адрес вытесняет и закрывает самый старый документ', async () => {
    const { result, rerender } = renderHook(({ url }) => useDocumentBackend(url), {
      initialProps: { url: 'u1' as string | null },
    });
    await waitFor(() => expect(result.current.backend).not.toBeNull());
    const first = result.current.backend;

    rerender({ url: 'u2' });
    await waitFor(() => expect(result.current.backend).not.toBe(first));
    await waitFor(() => expect(result.current.backend).not.toBeNull());
    const second = result.current.backend;
    expect(closed(first)).toBe(false);

    rerender({ url: 'u3' });
    await waitFor(() => expect(closed(first)).toBe(true));
    expect(closed(second)).toBe(false);
    expect(opened.calls).toBe(3);
  });

  it('прежняя ошибка не живёт после выключения: повторное открытие начинается с загрузки', async () => {
    opened.fail = true;
    const { result, rerender } = renderHook(({ url }) => useDocumentBackend(url), {
      initialProps: { url: 'u1' as string | null },
    });
    await waitFor(() => expect(result.current.errorCode).toBe('PDF_LOAD_FAILED'));

    rerender({ url: null });
    opened.fail = false;
    rerender({ url: 'u1' });
    expect(result.current.errorCode).toBeNull();
    await waitFor(() => expect(result.current.backend).not.toBeNull());
    expect(result.current.errorCode).toBeNull();
  });
});
