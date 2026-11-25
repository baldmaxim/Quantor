'use client';

import {
  readStoreySheets,
  type ModelSheetOverlayList,
  type ModelSheetOverlayRead,
} from '@quantor/api-client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Чертёж наложением на модель: листы планов на отметке этажа и их привязка к сетке осей модели
 * (портал подгоняет подобие по подписям осей вида листа). Матрица переводит pt страницы (от
 * левого верхнего угла) в мм системы здания модели; лист рисует pdf.js в браузере.
 */

/** [a, b, c, d, e, f]: x = a·x_pt + b·y_pt + c, y = d·x_pt + e·y_pt + f (мм модели). */
export type SheetMatrix = readonly [number, number, number, number, number, number];

export type Point2 = readonly [number, number];

/**
 * Ключ вне ['model', projectId]: метаданные модели обновляются опросом каждые 8 с, а привязку
 * листов портал считает заново - пересчитывать её от каждого опроса незачем.
 */
export const sheetOverlayKey = (projectId: string, versionId: string, storeyKey: string) =>
  ['model-sheets', projectId, versionId, storeyKey] as const;

const FIVE_MINUTES = 5 * 60 * 1000;

export const useStoreySheets = (
  projectId: string,
  versionId: string | null,
  storeyKey: string | null,
  enabled: boolean,
): UseQueryResult<ModelSheetOverlayList> =>
  useQuery({
    queryKey: sheetOverlayKey(projectId, versionId ?? '', storeyKey ?? ''),
    queryFn: async () =>
      unwrap(
        await readStoreySheets({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId ?? '', storey_key: storeyKey ?? '' },
        }),
      ),
    enabled: enabled && versionId !== null && storeyKey !== null,
    staleTime: FIVE_MINUTES,
    retry: 1,
  });

export const matrixOf = (item: ModelSheetOverlayRead): SheetMatrix | null => {
  const m = item.matrix;
  if (!m || m.length !== 6 || m.some((value) => !Number.isFinite(value))) return null;
  return [m[0], m[1], m[2], m[3], m[4], m[5]] as const;
};

export const applyMatrix = (m: SheetMatrix, x: number, y: number): Point2 => [
  m[0] * x + m[1] * y + m[2],
  m[3] * x + m[4] * y + m[5],
];

/**
 * Углы страницы в мм модели в порядке: левый верхний, правый верхний, правый нижний, левый
 * нижний (как идут строки растра). `width`/`height` - размер страницы в pt при масштабе 1.
 */
export const pageCornersMm = (
  m: SheetMatrix,
  width: number,
  height: number,
): [Point2, Point2, Point2, Point2] => [
  applyMatrix(m, 0, 0),
  applyMatrix(m, width, 0),
  applyMatrix(m, width, height),
  applyMatrix(m, 0, height),
];

/** Наибольшая сторона растра листа, пикселей: читаемо при подлёте и в пределах памяти видеокарты. */
export const MAX_SHEET_PIXELS = 4096;

/** Масштаб отрисовки страницы pdf.js, чтобы большая сторона растра была не больше предела. */
export const rasterScale = (width: number, height: number, limit = MAX_SHEET_PIXELS): number => {
  const side = Math.max(width, height);
  return side > 0 ? Math.min(limit / side, 4) : 1;
};

/** Подпись качества привязки для человека. */
export const fitLabel = (item: ModelSheetOverlayRead): string => {
  if (item.status !== 'registered') return item.reason ?? 'не привязан';
  const axes = item.axes_used?.length ?? 0;
  const rms = item.rms_mm ?? 0;
  const off = item.axes_rejected ?? [];
  const tail = off.length > 0 ? `; на листе не там, где в модели: ${off.join(', ')}` : '';
  return `по ${axes} осям, расхождение ${Math.round(rms)} мм${tail}`;
};

/** Что передаётся просмотрщику: растр листа и его углы на отметке этажа. */
export interface ISheetPlaneInput {
  readonly canvas: HTMLCanvasElement;
  /** Углы страницы в мм модели (левый верхний, правый верхний, правый нижний, левый нижний). */
  readonly corners: readonly Point2[];
  /** Отметка этажа модели, мм: лист кладётся чуть выше неё. */
  readonly elevationMm: number;
  /** Номер этажа для разноса этажей (как у частей этажа). */
  readonly level: number;
  readonly opacity: number;
  /** Ключ содержимого: тот же - растр не пересоздаётся при смене прозрачности. */
  readonly key: string;
}
