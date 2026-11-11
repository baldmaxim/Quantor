import type { CadPreviewRead } from '@quantor/api-client';

import type { ICadPaintData } from './cad-painter';
import { overlayPaths, type ICadFrame, type INormalizedPath, type IPageSize } from './frame';
import { isMepLayerHidden } from './mep-layers';

/**
 * Трассы механики на листе. `preview.json` трасс лежит в тех же миллиметрах и в той же рамке, что
 * предпросмотр DXF вида родителя, поэтому трассы кладутся тем же кадром и рисуются тем же
 * рисовальщиком CAD: к путям родителя добавляются пути трасс, слои трасс получают индексы после
 * слоёв родителя.
 */

export interface IRoutePaintInput {
  readonly preview: CadPreviewRead;
  /** Цвет слоя трасс по имени (из токенов темы). */
  readonly colors: Readonly<Record<string, string>>;
  /** Маска слоёв трасс, скрытых человеком. */
  readonly hiddenMask: number;
  /**
   * Уже нормализованные пути `preview` (слои - индексы самого превью, без сдвига). Считаются один
   * раз по превью, кадру и листу, чтобы смена маски не пересчитывала геометрию.
   */
  readonly paths?: readonly INormalizedPath[];
}

const NO_PATHS: readonly INormalizedPath[] = [];

/**
 * Склейка путей DXF вида и трасс со сдвигом слоёв трасс. Результат запоминается по тройке
 * (пути вида, пути трасс, сдвиг): массив один и тот же, пока те же исходные данные, и кеш
 * `Path2D` рисовальщика переживает смену маски слоёв.
 */
const mergedCache = new WeakMap<
  readonly INormalizedPath[],
  WeakMap<readonly INormalizedPath[], Map<number, readonly INormalizedPath[]>>
>();

const mergedPaths = (
  base: readonly INormalizedPath[],
  route: readonly INormalizedPath[],
  offset: number,
): readonly INormalizedPath[] => {
  let byBase = mergedCache.get(route);
  if (!byBase) {
    byBase = new WeakMap();
    mergedCache.set(route, byBase);
  }
  let byOffset = byBase.get(base);
  if (!byOffset) {
    byOffset = new Map();
    byBase.set(base, byOffset);
  }
  const cached = byOffset.get(offset);
  if (cached) return cached;
  const merged = [...base, ...route.map((path) => ({ ...path, layer: path.layer + offset }))];
  byOffset.set(offset, merged);
  return merged;
};

/**
 * Данные рисовальщика с трассами поверх DXF вида. Без трасс - `base` как есть. `base` пуст, а трассы
 * есть (DXF вида не накладывается) - рисуются одни трассы.
 */
export const mergeRoutePaint = (
  base: ICadPaintData | null,
  baseLayerCount: number,
  route: IRoutePaintInput | null,
  frame: ICadFrame | null,
  page: IPageSize | null,
  ink: string,
): ICadPaintData | null => {
  if (!route || !frame || !page) return base;
  const offset = base ? baseLayerCount : 0;
  const names = route.preview.layers;
  const routePaths = route.paths ?? overlayPaths(route.preview.paths, frame, page);

  const visible = new Set(base?.visibleLayers ?? []);
  names.forEach((name, index) => {
    if (!isMepLayerHidden(route.hiddenMask, name)) visible.add(offset + index);
  });
  const baseColors = Array.from(
    { length: offset },
    (_, index) => base?.layerColors[index] ?? base?.ink ?? ink,
  );

  return {
    paths: mergedPaths(base?.paths ?? NO_PATHS, routePaths, offset),
    visibleLayers: visible,
    opacity: base?.opacity ?? 1,
    layerColors: [...baseColors, ...names.map((name) => route.colors[name] ?? ink)],
    ink: base?.ink ?? ink,
    paper: base?.paper ?? null,
    crop: base?.crop ?? null,
  };
};
