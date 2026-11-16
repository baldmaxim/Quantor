import type { CalcElement, CalcPolyline, TenderViewLayerRead } from '@quantor/api-client';

/** Синтетические расчёты для тестов слоя «Расчёты» (данных объектов нет). */

export const polyline = (patch: Partial<CalcPolyline> = {}): CalcPolyline => ({
  id: 'T1-a',
  system: 'heating',
  layer: 'T-OV-T1',
  kind: 'route',
  shape: 'round',
  dn_mm: 20,
  pts: [
    [1000, 2000, 300],
    [5000, 2000, 300],
  ],
  ...patch,
});

export const element = (patch: Partial<CalcElement> = {}): CalcElement => ({
  id: 'KV-1',
  system: 'heating',
  type: 'terminal',
  subtype: 'convector',
  layer: 'T-OV-T1',
  pos: [5000, 2000, 100],
  axis: [1000, 0, 0],
  w_mm: 1500,
  length_mm: 300,
  h_mm: 110,
  mark: 'КВ-2',
  ...patch,
});

export const layer = (patch: Partial<TenderViewLayerRead> = {}): TenderViewLayerRead => ({
  version_id: 'v1',
  calc_id: 'c1',
  discipline: 'mech',
  system: 'heating',
  title: 'Отопление жилой части',
  number: 3,
  label: 'v3',
  floors: ['15'],
  base_stale: false,
  polylines: [polyline()],
  elements: [element()],
  ...patch,
});
