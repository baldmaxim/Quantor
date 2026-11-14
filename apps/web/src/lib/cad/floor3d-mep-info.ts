import { formatMeters } from './floor3d-geometry';
import type { IFloor3dMepElement } from './floor3d-mep-elements';
import {
  DN_SOURCE_LABELS,
  DN_SOURCE_UNKNOWN,
  ROUTE_KIND_LABELS,
  mepElementTitle,
} from './floor3d-mep-labels';
import type { IMepPick } from './floor3d-mep-pick';
import type { IFloor3dRoutePolyline } from './floor3d-routes';
import { mepLayerDef } from './mep-layers';
import { formatNumber } from './view-format';

/**
 * Содержимое плашки выбранной трассы или элемента ВИС: заголовок и строки «подпись: значение».
 * Чистые функции без React; подписи - в `floor3d-mep-labels.ts`.
 */

export interface IMepInfoRow {
  readonly label: string;
  readonly value: string;
}

export interface IMepInfo {
  readonly title: string;
  readonly rows: readonly IMepInfoRow[];
}

const positive = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

/** Система: подпись слоя из `mep-layers`; чужое имя слоя - как есть. */
export const systemLabel = (layer: string): string => mepLayerDef(layer)?.label ?? layer;

/** Длина полилинии по 3D-сегментам, м (вершины в мм). */
export const polylineLengthM = (pts: readonly (readonly number[])[]): number => {
  let total = 0;
  for (let i = 1; i < pts.length; i += 1) {
    const [ax, ay, az] = pts[i - 1] ?? [];
    const [bx, by, bz] = pts[i] ?? [];
    if (ax === undefined || ay === undefined || az === undefined) continue;
    if (bx === undefined || by === undefined || bz === undefined) continue;
    total += Math.hypot(bx - ax, by - ay, bz - az);
  }
  return total / 1000;
};

const rowOf = (label: string, value: string): IMepInfoRow => ({ label, value });

/**
 * Плашка трассы: система, вид, марка, сечение и его источник, изоляция, уклон, квартира, длина, отметки.
 * Линия ЭОМ и СС (есть изделие `item`) озаглавлена изделием; источника сечения и изоляции у неё нет.
 */
export const routeInfo = (polyline: IFloor3dRoutePolyline): IMepInfo => {
  const item = polyline.item ? polyline.item : null;
  const rows: IMepInfoRow[] = [rowOf('Система', systemLabel(polyline.layer))];
  const kind = polyline.kind == null ? undefined : ROUTE_KIND_LABELS[polyline.kind];
  if (kind !== undefined) rows.push(rowOf('Вид', kind));
  if (polyline.mark) rows.push(rowOf('Марка', polyline.mark));

  const source = polyline.dn_source == null ? DN_SOURCE_UNKNOWN : (DN_SOURCE_LABELS[polyline.dn_source] ?? DN_SOURCE_UNKNOWN);
  let halfHeightMm = 0;
  if (polyline.shape === 'rect') {
    const known = positive(polyline.w_mm) && positive(polyline.h_mm);
    rows.push(rowOf('Сечение', known ? `${polyline.w_mm}×${polyline.h_mm} мм` : 'не определено'));
    if (item === null) rows.push(rowOf('Источник сечения', source));
    if (positive(polyline.h_mm)) halfHeightMm = polyline.h_mm / 2;
  } else if (polyline.shape === 'round') {
    // Условный Ø для отрисовки (DISPLAY_DN_UNKNOWN_MM) в плашке не показывается.
    rows.push(rowOf('Диаметр', positive(polyline.dn_mm) ? `Ø ${polyline.dn_mm} мм` : 'Ø не определён'));
    if (item === null) rows.push(rowOf('Источник Ø', positive(polyline.dn_mm) ? source : DN_SOURCE_UNKNOWN));
    if (positive(polyline.dn_mm)) halfHeightMm = polyline.dn_mm / 2;
  }
  if (item === null) {
    rows.push(
      rowOf('Изоляция', positive(polyline.insulation_mm) ? `${polyline.insulation_mm} мм` : 'нет'),
    );
  }
  if (typeof polyline.slope === 'number' && Number.isFinite(polyline.slope)) {
    rows.push(
      rowOf(
        'Уклон',
        `${formatNumber(polyline.slope, 3)} (${formatNumber(polyline.slope * 1000, 1)} ‰)`,
      ),
    );
  }
  if (polyline.apt) rows.push(rowOf('Квартира', polyline.apt));
  rows.push(rowOf('Длина', formatNumber(polylineLengthM(polyline.pts), 2, 'м')));
  const zs = polyline.pts.flatMap((point) => (Number.isFinite(point[2]) ? [point[2] as number] : []));
  if (zs.length > 0) {
    rows.push(rowOf('Низ от чистого пола, м', formatMeters(Math.min(...zs) - halfHeightMm)));
    rows.push(rowOf('Верх от чистого пола, м', formatMeters(Math.max(...zs) + halfHeightMm)));
  }
  return { title: item ?? kind ?? 'Трасса', rows };
};

const sizeRows = (element: IFloor3dMepElement): IMepInfoRow[] => {
  const rows: IMepInfoRow[] = [];
  if (element.type === 'device' || element.type === 'box') {
    // Короб прибора ЭОМ и СС: ширина × высота × глубина вдоль нормали.
    if (positive(element.w_mm) && positive(element.h_mm) && positive(element.d_mm)) {
      rows.push(rowOf('Размеры', `${element.w_mm}×${element.h_mm}×${element.d_mm} мм`));
    }
    return rows;
  }
  if (element.type === 'terminal') {
    if (element.subtype === 'sprinkler') {
      if (positive(element.dn_mm)) rows.push(rowOf('Диаметр', `Ø ${element.dn_mm} мм`));
      if (positive(element.h_mm)) rows.push(rowOf('Высота', `${element.h_mm} мм`));
    } else if (positive(element.w_mm) && positive(element.length_mm) && positive(element.h_mm)) {
      rows.push(rowOf('Размеры', `${element.w_mm}×${element.length_mm}×${element.h_mm} мм`));
    }
    return rows;
  }
  if (positive(element.dn_mm)) rows.push(rowOf('Диаметр', `Ø ${element.dn_mm} мм`));
  if (positive(element.outer_d_mm)) rows.push(rowOf('Наружный диаметр', `Ø ${element.outer_d_mm} мм`));
  if (positive(element.w_mm) && positive(element.h_mm)) {
    rows.push(rowOf('Сечение', `${element.w_mm}×${element.h_mm} мм`));
  }
  if (positive(element.length_mm)) rows.push(rowOf('Длина', `${element.length_mm} мм`));
  return rows;
};

/**
 * Плашка элемента: название по-русски, система, размеры, квартира, марка. Название от генератора
 * (`name`, у ЭОМ и СС) главнее подписи по подтипу.
 */
export const elementInfo = (element: IFloor3dMepElement): IMepInfo => {
  const rows: IMepInfoRow[] = [rowOf('Система', systemLabel(element.layer)), ...sizeRows(element)];
  if (element.apt) rows.push(rowOf('Квартира', element.apt));
  if (element.mark) rows.push(rowOf('Марка', element.mark));
  const title = element.name ? element.name : mepElementTitle(element.type, element.subtype);
  return { title, rows };
};

/** Содержимое плашки по выбору; `null` - выбранного нет в данных (трассы перечитаны). */
export const mepInfoOf = (
  pick: IMepPick,
  data: {
    readonly polylines: readonly IFloor3dRoutePolyline[];
    readonly elements?: readonly IFloor3dMepElement[];
  },
): IMepInfo | null => {
  if (pick.kind === 'route') {
    const polyline = data.polylines[pick.index];
    return polyline === undefined ? null : routeInfo(polyline);
  }
  const element = data.elements?.[pick.index];
  return element === undefined ? null : elementInfo(element);
};
