import { fireEvent } from '@testing-library/react';

import type { CadZoneRead } from '@quantor/api-client';

/** Зона-помещение для тестов режимов правки и разреза: квадрат 0.2..0.6 на листе 1000 x 1000. */
export const zoneFixture = (patch: Partial<CadZoneRead> = {}): CadZoneRead => ({
  id: 'z1',
  revision_id: 'r1',
  page_index: 0,
  kind: 'room_mop',
  apartment_no: null,
  room_mark: null,
  name: null,
  points: [
    [0.2, 0.2],
    [0.6, 0.2],
    [0.6, 0.6],
    [0.2, 0.6],
  ],
  door_height_mm: null,
  finish_template_id: null,
  parking_type: null,
  room_type: null,
  room_type_source: null,
  area_m2: null,
  perimeter_m: null,
  width_m: null,
  calibration_missing: true,
  geometry_issue: null,
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
  ...patch,
});

const MOUSE = { pointerId: 1, button: 0, pointerType: 'mouse' } as const;

export const pointerDown = (layer: HTMLElement, x: number, y: number) =>
  fireEvent.pointerDown(layer, { ...MOUSE, clientX: x, clientY: y });
export const pointerMove = (layer: HTMLElement, x: number, y: number) =>
  fireEvent.pointerMove(layer, { ...MOUSE, clientX: x, clientY: y });
export const pointerUp = (layer: HTMLElement, x: number, y: number) =>
  fireEvent.pointerUp(layer, { ...MOUSE, clientX: x, clientY: y });

export const tap = (layer: HTMLElement, x: number, y: number) => {
  pointerDown(layer, x, y);
  pointerUp(layer, x, y);
};

/** Перетаскивание из точки в точку тремя событиями указателя. */
export const drag = (
  layer: HTMLElement,
  from: readonly [number, number],
  to: readonly [number, number],
) => {
  pointerDown(layer, from[0], from[1]);
  pointerMove(layer, to[0], to[1]);
  pointerUp(layer, to[0], to[1]);
};

/** Заглушки API указателя и холста, которых нет в jsdom. */
export const stubPointerApi = (): void => {
  HTMLElement.prototype.setPointerCapture = () => undefined;
  HTMLElement.prototype.releasePointerCapture = () => undefined;
  HTMLElement.prototype.hasPointerCapture = () => false;
  HTMLCanvasElement.prototype.getContext = () => null;
};
