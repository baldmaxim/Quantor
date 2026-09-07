'use client';

import { useEffect, useState } from 'react';

import type { PageGeometry, RenderBackend } from '@/lib/viewer/backend';

interface Loaded {
  readonly backend: RenderBackend;
  readonly pageIndex: number;
  readonly geometry: PageGeometry;
}

/**
 * Размер страницы, как его видит отрисовщик.
 *
 * Нужен и холсту, и кнопкам «По ширине»/«Целиком», поэтому живёт выше обоих. Брать
 * размер из полей `width_px`/`height_px` распознанного пакета нельзя: это пиксели
 * растра, снятого с непостоянной плотностью, а не единицы документа.
 *
 * Устаревший результат отсеивается сравнением при отрисовке, а не сбросом состояния
 * в эффекте: сброс дал бы лишний каскад перерисовок на каждой смене листа.
 */
export const usePageGeometry = (
  backend: RenderBackend | null,
  pageIndex: number | null,
): PageGeometry | null => {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    if (!backend || pageIndex === null) return;

    let cancelled = false;
    void backend
      .geometry(pageIndex)
      .then((geometry) => {
        if (!cancelled) setLoaded({ backend, pageIndex, geometry });
      })
      .catch(() => {
        // Отказ разбирается отрисовкой: там он превращается в код ошибки на экране.
      });

    return () => {
      cancelled = true;
    };
  }, [backend, pageIndex]);

  if (!loaded || loaded.backend !== backend || loaded.pageIndex !== pageIndex) return null;
  return loaded.geometry;
};
