'use client';

import { useEffect, useState } from 'react';

import type { CadPreviewRead } from '@quantor/api-client';

import type { ICadFrame, IPageSize } from '@/lib/cad/frame';
import type { ISnapIndex } from '@/lib/cad/zone-snap';
import { buildWallSnapIndex } from '@/lib/cad/zone-snap-walls';

interface IBuilt {
  readonly preview: CadPreviewRead;
  readonly frame: ICadFrame;
  readonly page: IPageSize;
  readonly index: ISnapIndex | null;
}

/**
 * Индекс углов и граней стен открытого листа для привязки при рисовании зон.
 *
 * Строится только когда рисование включено, и не в рендере, а следующей задачей: режим
 * открывается сразу, стены подключаются, как только индекс готов. Результат помнится до смены
 * (предпросмотр, кадр, страница), поэтому повторное включение режима мгновенно. Нет предпросмотра
 * или кадра - `null`, привязка работает только к зонам.
 */
export const useWallSnapIndex = (
  preview: CadPreviewRead | null,
  frame: ICadFrame | null,
  page: IPageSize | null,
  enabled: boolean,
): ISnapIndex | null => {
  const [built, setBuilt] = useState<IBuilt | null>(null);
  const fresh =
    built !== null && built.preview === preview && built.frame === frame && built.page === page;

  useEffect(() => {
    if (!enabled || fresh || !preview || !frame || !page) return undefined;
    const timer = setTimeout(
      () => setBuilt({ preview, frame, page, index: buildWallSnapIndex(preview, frame, page) }),
      0,
    );
    return () => clearTimeout(timer);
  }, [enabled, fresh, preview, frame, page]);

  return enabled && fresh ? built.index : null;
};
