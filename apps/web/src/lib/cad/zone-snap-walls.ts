/**
 * Цели привязки зон на стенах листа: углы (вершины контуров стен) и грани (их отрезки).
 *
 * Источник - предпросмотр CAD-вида (`quantor.cad_engine.preview.v1`): слой `01_КОНТУРЫ_СТЕН`
 * (основной) и слои `02_МОНОЛИТ…`; слои сопоставляются по ИМЕНИ, не по номеру, слои контроля
 * качества `QA_…` игнорируются. Точки DXF (мм) переводятся в нормализованные координаты листа
 * тем же кадром, что и наложение (frame.ts, ось Y переворачивается там же).
 */

import type { CadPreviewRead } from '@quantor/api-client';

import { cadToNormalized, type ICadFrame, type IPageSize } from '@/lib/cad/frame';
import { buildSnapIndex, type ISnapIndex, type ISnapShape } from '@/lib/cad/zone-snap';

const WALL_CONTOURS_LAYER = '01_КОНТУРЫ_СТЕН';
const MONOLITH_LAYER_PREFIX = '02_МОНОЛИТ';
const QA_PREFIX = 'QA_';

/** Слой стен для привязки: контуры стен и монолит, без слоёв контроля качества. */
export const isWallSnapLayer = (name: string): boolean => {
  const value = name.trim().toUpperCase();
  if (value.startsWith(QA_PREFIX)) return false;
  return value === WALL_CONTOURS_LAYER || value.startsWith(MONOLITH_LAYER_PREFIX);
};

/** Контуры стен предпросмотра в нормализованных координатах листа. */
export const wallSnapShapes = (
  preview: CadPreviewRead,
  frame: ICadFrame,
  page: IPageSize,
): ISnapShape[] => {
  const wallLayers = new Set<number>();
  preview.layers.forEach((name, index) => {
    if (isWallSnapLayer(name)) wallLayers.add(index);
  });
  if (wallLayers.size === 0) return [];

  const shapes: ISnapShape[] = [];
  for (const path of preview.paths) {
    if (!wallLayers.has(path.layer)) continue;
    const count = Math.floor(path.points.length / 2);
    if (count < 2) continue;
    const points: [number, number][] = [];
    for (let at = 0; at < count; at += 1) {
      const point = cadToNormalized(
        frame,
        page,
        path.points[at * 2] ?? 0,
        path.points[at * 2 + 1] ?? 0,
      );
      if (Number.isFinite(point[0]) && Number.isFinite(point[1])) points.push(point);
    }
    if (points.length >= 2) shapes.push({ points, closed: path.closed });
  }
  return shapes;
};

/**
 * Индекс углов и граней стен; `null` - в виде нет слоёв стен (привязка к стенам выключена).
 * Строить один раз на смену (предпросмотр, кадр, страница): точек на реальном листе десятки тысяч.
 */
export const buildWallSnapIndex = (
  preview: CadPreviewRead | null,
  frame: ICadFrame | null,
  page: IPageSize | null,
): ISnapIndex | null => {
  if (!preview || !frame || !page || !(page.width > 0) || !(page.height > 0)) return null;
  const shapes = wallSnapShapes(preview, frame, page);
  return shapes.length > 0 ? buildSnapIndex(shapes) : null;
};
