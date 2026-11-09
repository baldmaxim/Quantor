import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RenderBackend } from '@/lib/viewer/backend';

const opened = vi.hoisted(() => ({
  list: [] as { destroyed: boolean; destroy: () => void }[],
  fail: false,
}));

vi.mock('@/lib/viewer/pdfjs-backend', () => ({
  PdfJsRenderBackend: {
    open: async () => {
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

import { useDocumentBackend } from './useDocumentBackend';

beforeEach(() => {
  opened.list = [];
  opened.fail = false;
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

  it('выключили и включили тот же адрес: закрытый отрисовщик не возвращается', async () => {
    const { result, rerender } = renderHook(({ url }) => useDocumentBackend(url), {
      initialProps: { url: 'u1' as string | null },
    });
    await waitFor(() => expect(result.current.backend).not.toBeNull());
    const first = result.current.backend;

    rerender({ url: null });
    expect(result.current.backend).toBeNull();
    expect(closed(first)).toBe(true);

    rerender({ url: 'u1' });
    // В первом же кадре после возврата - загрузка, а не мёртвый объект.
    expect(result.current.backend).toBeNull();
    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.backend).not.toBeNull());
    expect(result.current.backend).not.toBe(first);
    expect(closed(result.current.backend)).toBe(false);
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
