'use client';

import { useMemo } from 'react';

import { useDocumentBackend } from '@/components/viewer/useDocumentBackend';
import { usePageGeometry } from '@/components/viewer/usePageGeometry';
import { extractCode } from '@/lib/errors';
import { useContentUrl } from '@/lib/queries';
import type { RenderBackend } from '@/lib/viewer/backend';

/**
 * Страница исходного PDF ревизии через общий стек просмотрщика.
 * Размер листа берётся у отрисовщика, а не из пакета распознавания (ADR-0008).
 *
 * Отрисовщик живёт всё время жизни панели вида: переключение режима PDF/CAD/наложение его не
 * закрывает и не открывает заново, режим лишь решает, показывать ли слой PDF.
 */

export interface ICadPdfPage {
  readonly backend: RenderBackend | null;
  readonly sheet: { readonly pageIndex: number; readonly width: number; readonly height: number } | null;
  readonly loading: boolean;
  /** Код отказа или `null`. */
  readonly errorCode: string | null;
  /** В PDF нет страницы с таким номером. */
  readonly outOfRange: boolean;
}

export const useCadPdfPage = (revisionId: string, pageIndex: number): ICadPdfPage => {
  const content = useContentUrl(revisionId);
  const document = useDocumentBackend(content.data?.url ?? null);
  const outOfRange =
    document.backend !== null && (pageIndex < 0 || pageIndex >= document.backend.pageCount);
  const geometry = usePageGeometry(document.backend, outOfRange ? null : pageIndex);

  const width = geometry?.width ?? null;
  const height = geometry?.height ?? null;
  const sheet = useMemo(
    () => (width !== null && height !== null ? { pageIndex, width, height } : null),
    [pageIndex, width, height],
  );

  const errorCode = content.isError ? extractCode(content.error) : document.errorCode;

  return {
    backend: document.backend,
    sheet,
    loading: errorCode === null && !outOfRange && sheet === null,
    errorCode,
    outOfRange,
  };
};
