'use client';

import { useEffect, useState } from 'react';

import type { RenderBackend } from '@/lib/viewer/backend';

/**
 * Открытие документа отрисовщиком.
 *
 * pdf.js подгружается динамически и только здесь: он вместе с рабочим потоком весит
 * заметно, и на списке проектов он не нужен. Импорт внутри эффекта — это и есть та самая
 * ленивая загрузка, ради которой в ADR-0004 разделены слои.
 */

interface Loaded {
  /** Адрес, для которого получен отрисовщик. По нему же вычисляется признак загрузки. */
  readonly url: string | null;
  readonly backend: RenderBackend | null;
  readonly errorCode: string | null;
}

interface BackendState {
  readonly backend: RenderBackend | null;
  readonly loading: boolean;
  readonly errorCode: string | null;
}

const EMPTY: Loaded = { url: null, backend: null, errorCode: null };

export const useDocumentBackend = (url: string | null): BackendState => {
  const [loaded, setLoaded] = useState<Loaded>(EMPTY);

  useEffect(() => {
    if (!url) return;

    let disposed = false;
    let opened: RenderBackend | null = null;
    const controller = new AbortController();

    void (async () => {
      try {
        const { PdfJsRenderBackend } = await import('@/lib/viewer/pdfjs-backend');
        const backend = await PdfJsRenderBackend.open(url, controller.signal);

        if (disposed) {
          backend.destroy();
          return;
        }
        opened = backend;
        setLoaded({ url, backend, errorCode: null });
      } catch (error) {
        if (disposed) return;
        setLoaded({ url, backend: null, errorCode: codeOf(error) });
      }
    })();

    return () => {
      disposed = true;
      controller.abort();
      // Документ закрывается явно: pdf.js держит рабочий поток и буферы страниц,
      // и без этого при смене ссылки они накапливаются.
      opened?.destroy();
    };
  }, [url]);

  // Признак загрузки выводится, а не хранится: иначе пришлось бы менять состояние прямо
  // в теле эффекта и получать лишний каскад отрисовок.
  const loading = url !== null && loaded.url !== url;

  return {
    backend: loading ? null : loaded.backend,
    loading,
    errorCode: loading ? null : loaded.errorCode,
  };
};

const codeOf = (error: unknown): string =>
  typeof error === 'object' && error !== null && 'code' in error
    ? String((error as { code: unknown }).code)
    : 'PDF_LOAD_FAILED';
