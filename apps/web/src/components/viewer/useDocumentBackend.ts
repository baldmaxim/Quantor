'use client';

import { useEffect, useState } from 'react';

import type { RenderBackend } from '@/lib/viewer/backend';

/**
 * Открытие документа отрисовщиком.
 *
 * Открытые документы кешируются на уровне модуля (до двух, LRU), а не закрываются при
 * размонтировании: возврат в рабочую область к тому же листу не открывает PDF с нуля.
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

/** Сколько открытых документов держим. Чертёж тяжёлый, но возврат «проект → лист» должен быть мгновенным. */
const DOCUMENT_CACHE_LIMIT = 2;

/**
 * Кеш открытых документов по адресу. Хранится промис, а не сам отрисовщик: два параллельных
 * монтирования (например, строгий режим) не откроют один файл дважды. Порядок вставки Map —
 * порядок давности использования: первым вытесняется самый старый.
 */
const documentCache = new Map<string, Promise<RenderBackend>>();

const closeLater = (pending: Promise<RenderBackend>): void => {
  pending.then(
    (backend) => backend.destroy(),
    () => undefined,
  );
};

const acquireBackend = (url: string): Promise<RenderBackend> => {
  const cached = documentCache.get(url);
  if (cached) {
    // Обращение освежает запись: она становится самой новой.
    documentCache.delete(url);
    documentCache.set(url, cached);
    return cached;
  }

  // Сигнал отмены сюда не передаём: документ общий, и уход одного потребителя не должен
  // его закрывать. Если потребитель ушёл до открытия, документ всё равно доедет в кеш.
  const pending = (async () => {
    const { PdfJsRenderBackend } = await import('@/lib/viewer/pdfjs-backend');
    return PdfJsRenderBackend.open(url);
  })();
  documentCache.set(url, pending);

  // Ошибку открытия в кеше не держим: повторная попытка должна открыть документ заново.
  pending.catch(() => {
    if (documentCache.get(url) === pending) documentCache.delete(url);
  });

  while (documentCache.size > DOCUMENT_CACHE_LIMIT) {
    const oldest = documentCache.keys().next().value;
    if (oldest === undefined) break;
    const evicted = documentCache.get(oldest);
    documentCache.delete(oldest);
    if (evicted) closeLater(evicted);
  }
  return pending;
};

/** Закрывает и очищает кеш документов. Только для тестов. */
export const resetDocumentCacheForTests = (): void => {
  for (const pending of documentCache.values()) closeLater(pending);
  documentCache.clear();
};

export const useDocumentBackend = (url: string | null): BackendState => {
  const [loaded, setLoaded] = useState<Loaded>(EMPTY);

  useEffect(() => {
    if (!url) return;

    let disposed = false;

    void (async () => {
      try {
        const backend = await acquireBackend(url);
        if (disposed) return;
        setLoaded({ url, backend, errorCode: null });
      } catch (error) {
        if (disposed) return;
        setLoaded({ url, backend: null, errorCode: codeOf(error) });
      }
    })();

    return () => {
      disposed = true;
      // Документ не закрывается: он остаётся в кеше, и возврат к тому же адресу не открывает
      // файл заново. Закрывает его только вытеснение из кеша (pdf.js держит рабочий поток
      // и буферы страниц, поэтому число открытых документов ограничено).
      // Состояние этого адреса сбрасывается: до получения отрисовщика из кеша показывается
      // загрузка, а не прежняя ошибка или отрисовщик другого прохода.
      setLoaded((current) => (current.url === url ? EMPTY : current));
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
