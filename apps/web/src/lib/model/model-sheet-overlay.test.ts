import type { ModelSheetOverlayRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  applyMatrix,
  fitLabel,
  matrixOf,
  pageCornersMm,
  rasterScale,
  type SheetMatrix,
} from './model-sheet-overlay';

const MM_PER_PT = (100 * 25.4) / 72;

/** Подобие как у портала: модель = R(θ)·diag(s, −s)·pt + t. */
const similarity = (thetaDeg: number, s: number, tx: number, ty: number): SheetMatrix => {
  const c = Math.cos((thetaDeg * Math.PI) / 180);
  const n = Math.sin((thetaDeg * Math.PI) / 180);
  return [s * c, s * n, tx, s * n, -s * c, ty];
};

const item = (patch: Partial<ModelSheetOverlayRead>): ModelSheetOverlayRead => ({
  revision_id: 'r',
  document_id: null,
  job_id: 'j',
  page_index: 92,
  view: 1,
  label: 'К5 · 17 эт.',
  group_label: 'Корп. 5',
  base_z_mm: 65850,
  status: 'registered',
  reason: null,
  matrix: [...similarity(0, MM_PER_PT, 1000, 2000)],
  rotation_deg: 0,
  scale_mm_per_pt: MM_PER_PT,
  frame_scale_mm_per_pt: MM_PER_PT,
  rms_mm: 12.4,
  max_mm: 30,
  axes_used: ['5/1', '5/2', '5/А', '5/Б'],
  ...patch,
});

describe('model-sheet-overlay', () => {
  it('углы страницы: ось Y листа вниз - на север модели вверх', () => {
    const m = similarity(0, MM_PER_PT, 1000, 2000);
    const [tl, tr, br, bl] = pageCornersMm(m, 2384, 1684);
    expect(tl).toEqual([1000, 2000]);
    expect(tr[0]).toBeCloseTo(1000 + 2384 * MM_PER_PT, 6);
    expect(tr[1]).toBeCloseTo(2000, 6);
    expect(br[1]).toBeCloseTo(2000 - 1684 * MM_PER_PT, 6);
    expect(bl[0]).toBeCloseTo(1000, 6);
  });

  it('повёрнутый корпус (−7°): длины сторон сохраняются', () => {
    const m = similarity(353, MM_PER_PT, 80000, 120000);
    const [tl, tr, br] = pageCornersMm(m, 2384, 1684);
    expect(Math.hypot(tr[0] - tl[0], tr[1] - tl[1])).toBeCloseTo(2384 * MM_PER_PT, 4);
    expect(Math.hypot(br[0] - tr[0], br[1] - tr[1])).toBeCloseTo(1684 * MM_PER_PT, 4);
    expect(applyMatrix(m, 0, 0)).toEqual([80000, 120000]);
  });

  it('матрица ответа: шесть конечных чисел, иначе null', () => {
    expect(matrixOf(item({}))).not.toBeNull();
    expect(matrixOf(item({ matrix: null }))).toBeNull();
    expect(matrixOf(item({ matrix: [1, 0, 0, 0, 1, Number.NaN] }))).toBeNull();
  });

  it('растр не больше 4096 px по большей стороне', () => {
    expect(rasterScale(2384, 1684) * 2384).toBeCloseTo(4096, 6);
    expect(rasterScale(100, 50)).toBe(4);
    expect(rasterScale(0, 0)).toBe(1);
  });

  it('подпись качества: по скольким осям и расхождение; не привязанный - причина', () => {
    expect(fitLabel(item({}))).toBe('по 4 осям, расхождение 12 мм');
    expect(fitLabel(item({ status: 'unregistered', reason: 'совпала одна ось' }))).toBe(
      'совпала одна ось',
    );
  });
});
