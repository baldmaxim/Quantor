'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import type { ZoneCategory } from '@/lib/cad/zone-categories';
import type { IZoneLabelOptions } from '@/lib/cad/zone-labels';
import {
  readStoredZoneView,
  writeStoredZoneView,
  type IZoneView,
  type ZoneColorMode,
} from '@/lib/cad/zone-view';

export interface IZoneViewState {
  readonly view: IZoneView;
  readonly onColorModeChange: (mode: ZoneColorMode) => void;
  /** Скрыть или показать категории разом. */
  readonly onSetHidden: (categories: readonly ZoneCategory[], hidden: boolean) => void;
  readonly onLabelsOnChange: (on: boolean) => void;
  readonly onLabelChange: (key: keyof IZoneLabelOptions, on: boolean) => void;
}

/**
 * Вид зон листа (окраска, скрытые категории, подписи) с сохранением в localStorage. На сервере и
 * без хранилища - умолчание (`readStoredZoneView` не бросает). Колбэки стабильны.
 */
export const useZoneView = (): IZoneViewState => {
  const [view, setView] = useState<IZoneView>(readStoredZoneView);

  useEffect(() => {
    writeStoredZoneView(view);
  }, [view]);

  const onColorModeChange = useCallback(
    (colorMode: ZoneColorMode) => setView((current) => ({ ...current, colorMode })),
    [],
  );
  const onSetHidden = useCallback(
    (categories: readonly ZoneCategory[], hidden: boolean) =>
      setView((current) => {
        const next = new Set(current.hidden);
        categories.forEach((category) => {
          if (hidden) next.add(category);
          else next.delete(category);
        });
        return { ...current, hidden: next };
      }),
    [],
  );
  const onLabelsOnChange = useCallback(
    (labelsOn: boolean) => setView((current) => ({ ...current, labelsOn })),
    [],
  );
  const onLabelChange = useCallback(
    (key: keyof IZoneLabelOptions, on: boolean) =>
      setView((current) => ({ ...current, labels: { ...current.labels, [key]: on } })),
    [],
  );

  return useMemo(
    () => ({ view, onColorModeChange, onSetHidden, onLabelsOnChange, onLabelChange }),
    [view, onColorModeChange, onSetHidden, onLabelsOnChange, onLabelChange],
  );
};
