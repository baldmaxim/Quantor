'use client';

import { type FC } from 'react';

import type { ZoneCategory } from '@/lib/cad/zone-categories';
import { ZONE_CATEGORY_LABELS, zoneCategoryColorVar } from '@/lib/cad/zone-categories';
import type { IZoneLabelOptions } from '@/lib/cad/zone-labels';
import type { IZoneView, ZoneColorMode } from '@/lib/cad/zone-view';

import { CadLayerGroup } from './CadLayerGroup';

/** Блок «Зоны» панели «Слои»: что есть на листе, вид и подписи. */
export interface ICadZoneLayers {
  /** Категории, которые есть на листе, с числом зон. */
  readonly categories: readonly { readonly category: ZoneCategory; readonly count: number }[];
  readonly view: IZoneView;
  readonly onSetHidden: (categories: readonly ZoneCategory[], hidden: boolean) => void;
  readonly onColorModeChange: (mode: ZoneColorMode) => void;
  readonly onLabelsOnChange: (on: boolean) => void;
  readonly onLabelChange: (key: keyof IZoneLabelOptions, on: boolean) => void;
}

const CHECK = 'flex min-h-[44px] items-center gap-[var(--s-3)] text-sm';

const COLOR_MODES: readonly { readonly mode: ZoneColorMode; readonly label: string }[] = [
  { mode: 'category', label: 'По типу помещения' },
  { mode: 'apartment', label: 'По квартирам' },
];

const LABEL_FLAGS: readonly { readonly key: keyof IZoneLabelOptions; readonly label: string }[] = [
  { key: 'apartment', label: '№ квартиры' },
  { key: 'mark', label: 'Марка' },
  { key: 'name', label: 'Название' },
  { key: 'area', label: 'Площадь' },
];

export const CadZoneLayers: FC<ICadZoneLayers> = ({
  categories,
  view,
  onSetHidden,
  onColorModeChange,
  onLabelsOnChange,
  onLabelChange,
}) => {
  const indices = categories.map((_, index) => index);
  const visible = new Set(indices.filter((index) => !view.hidden.has(categories[index]!.category)));
  const titles = categories.map(
    ({ category, count }) => `${ZONE_CATEGORY_LABELS[category]} (${count})`,
  );
  const byIndices = (list: readonly number[]) => list.map((index) => categories[index]!.category);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)]" data-testid="zone-layers">
      <fieldset className="min-w-0 border-0 p-0">
        <legend className="sr-only">Зоны по типам</legend>
        <CadLayerGroup
          group={{ key: 'zones', label: 'Зоны', indices }}
          layers={titles}
          visibleLayers={visible}
          onToggleLayer={(index) => {
            const category = categories[index]?.category;
            if (category !== undefined) onSetHidden([category], !view.hidden.has(category));
          }}
          onSetLayersHidden={(list, hidden) => onSetHidden(byIndices(list), hidden)}
          swatchColor={(index) => zoneCategoryColorVar(categories[index]?.category ?? 'other')}
        />
      </fieldset>

      <fieldset className="min-w-0 border-0 p-0">
        <legend className="mb-[var(--s-1)] text-xs text-muted">Цвет зон</legend>
        {COLOR_MODES.map(({ mode, label }) => (
          <label key={mode} className={CHECK}>
            <input
              type="radio"
              name="zone-color-mode"
              checked={view.colorMode === mode}
              onChange={() => onColorModeChange(mode)}
              className="size-5 shrink-0"
            />
            {label}
          </label>
        ))}
      </fieldset>

      <fieldset className="min-w-0 border-0 p-0">
        <legend className="sr-only">Подписи зон</legend>
        <label className={CHECK}>
          <input
            type="checkbox"
            checked={view.labelsOn}
            onChange={(event) => onLabelsOnChange(event.target.checked)}
            className="size-5 shrink-0"
          />
          Подписи зон
        </label>
        <div className="flex flex-col pl-[var(--s-6)]">
          {LABEL_FLAGS.map(({ key, label }) => (
            <label key={key} className={CHECK}>
              <input
                type="checkbox"
                checked={view.labels[key]}
                disabled={!view.labelsOn}
                onChange={(event) => onLabelChange(key, event.target.checked)}
                className="size-5 shrink-0"
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  );
};
