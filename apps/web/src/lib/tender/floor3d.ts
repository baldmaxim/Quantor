import type { CalcElement, CalcPolyline } from '@quantor/api-client';

import type { IFloor3dMepElement } from '@/lib/cad/floor3d-mep-elements';
import type { IFloor3dRoutePolyline } from '@/lib/cad/floor3d-routes';

import { sourceOf, type ITenderLayerData } from './geometry';
import type { ITenderRef, ITenderSource } from './info';
import { systemColorToken } from './systems';
import { tenderLayerKey } from './view-key';

/**
 * Геометрия расчёта -> вход построителей 3D этажа (`floor3d-routes.ts`, `floor3d-mep-elements.ts`):
 * формат расчёта - надмножество `routes3d.v2`, поэтому перевод почти тождественный. Слой в сцене -
 * `tender:<calc_id>` (один слой на расчёт: по нему же скрытие и цвет системы).
 *
 * Постановка в здание: точка объекта = `R(rotation_deg) · точка вида + offset_mm`, `z` - от чистого
 * пола этажа, отметка этажа прибавляется построителем (`baseZMm`).
 */

/** Постановка этажа в систему здания; у одного листа вне здания - тождественная. */
export interface ITenderPlacement {
  readonly offsetMm: readonly [number, number];
  readonly rotationDeg: number;
}

export const IDENTITY_PLACEMENT: ITenderPlacement = { offsetMm: [0, 0], rotationDeg: 0 };

/** Постановка этажа здания из ответа сервера (`offset_mm`, `rotation_deg`). */
export const placementOf = (floor: {
  readonly offset_mm: readonly [number, number];
  readonly rotation_deg?: number;
}): ITenderPlacement => ({ offsetMm: floor.offset_mm, rotationDeg: floor.rotation_deg ?? 0 });

const isIdentity = (placement: ITenderPlacement): boolean =>
  placement.rotationDeg === 0 && placement.offsetMm[0] === 0 && placement.offsetMm[1] === 0;

const placePoint = (
  placement: ITenderPlacement,
  x: number,
  y: number,
): readonly [number, number] => {
  const radians = (placement.rotationDeg * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return [
    cos * x - sin * y + placement.offsetMm[0],
    sin * x + cos * y + placement.offsetMm[1],
  ];
};

/** Точка вида `[x, y, z]` в системе здания; `z` не меняется. */
export const placeVertex = (
  placement: ITenderPlacement,
  point: readonly [number, number, number],
): [number, number, number] => {
  const [x, y] = placePoint(placement, point[0], point[1]);
  return [x, y, point[2]];
};

/** Ось (единичный вектор × 1000) после поворота этажа. */
const placeAxis = (
  placement: ITenderPlacement,
  axis: readonly [number, number, number],
): [number, number, number] => {
  const radians = (placement.rotationDeg * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return [cos * axis[0] - sin * axis[1], sin * axis[0] + cos * axis[1], axis[2]];
};

/** Этаж повёрнут на нечётное число четвертей: стороны коробки `w` и `length` меняются местами. */
const quarterTurned = (placement: ITenderPlacement): boolean =>
  Math.abs(Math.sin((placement.rotationDeg * Math.PI) / 180)) > Math.SQRT1_2;

const DEFAULT_AXIS: readonly [number, number, number] = [1000, 0, 0];

export const polylineOf = (
  polyline: CalcPolyline,
  source: ITenderSource,
  placement: ITenderPlacement,
): IFloor3dRoutePolyline => {
  const ref: ITenderRef = { source, object: { kind: 'polyline', data: polyline } };
  return {
    layer: tenderLayerKey(source.calcId),
    pts: isIdentity(placement) ? polyline.pts : polyline.pts.map((p) => placeVertex(placement, p)),
    shape: polyline.shape ?? null,
    dn_mm: polyline.dn_mm ?? null,
    w_mm: polyline.w_mm ?? null,
    h_mm: polyline.h_mm ?? null,
    insulation_mm: polyline.insulation_mm ?? null,
    kind: polyline.kind,
    mark: polyline.mark ?? null,
    slope: polyline.slope ?? null,
    apt: polyline.apt ?? null,
    tender: ref,
  };
};

export const elementOf = (
  element: CalcElement,
  source: ITenderSource,
  placement: ITenderPlacement,
): IFloor3dMepElement => {
  const ref: ITenderRef = { source, object: { kind: 'element', data: element } };
  const swap = quarterTurned(placement);
  return {
    type: element.type,
    subtype: element.subtype ?? '',
    layer: tenderLayerKey(source.calcId),
    pos: isIdentity(placement) ? element.pos : placeVertex(placement, element.pos),
    axis: placeAxis(placement, element.axis ?? DEFAULT_AXIS),
    dn_mm: element.dn_mm ?? null,
    w_mm: swap ? (element.length_mm ?? null) : (element.w_mm ?? null),
    length_mm: swap ? (element.w_mm ?? null) : (element.length_mm ?? null),
    h_mm: element.h_mm ?? null,
    apt: element.apt ?? null,
    mark: element.mark ?? null,
    tender: ref,
  };
};

export interface ITenderFloor3dInput {
  readonly polylines: IFloor3dRoutePolyline[];
  readonly elements: IFloor3dMepElement[];
  /** Слой сцены -> токен цвета системы (`readFloor3dRouteColors`). */
  readonly layerTokens: Record<string, string>;
}

/** Геометрия слоёв расчётов, поставленная в систему этажа или здания. */
export const tenderFloor3dInput = (
  layers: readonly ITenderLayerData[],
  placement: ITenderPlacement = IDENTITY_PLACEMENT,
): ITenderFloor3dInput => {
  const polylines: IFloor3dRoutePolyline[] = [];
  const elements: IFloor3dMepElement[] = [];
  const layerTokens: Record<string, string> = {};
  for (const layer of layers) {
    const source = sourceOf(layer);
    layerTokens[tenderLayerKey(layer.calc_id)] = systemColorToken(layer.system);
    for (const polyline of layer.polylines) polylines.push(polylineOf(polyline, source, placement));
    for (const element of layer.elements) elements.push(elementOf(element, source, placement));
  }
  return { polylines, elements, layerTokens };
};
