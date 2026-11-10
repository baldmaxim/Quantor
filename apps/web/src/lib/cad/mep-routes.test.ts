import type { CadPreviewRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import type { ICadPaintData } from './cad-painter';
import type { ICadFrame } from './frame';
import { withMepLayersHidden } from './mep-layers';
import { mergeRoutePaint } from './mep-routes';
import { isRouteJob, routeJobLabel } from './mep-jobs';
import { latestSheetJobs } from './sheet-results';

const frame: ICadFrame = { originX: 0, originY: 100, mmPerPt: 10 };
const page = { width: 200, height: 100 };

const base: ICadPaintData = {
  paths: [
    { layer: 0, closed: false, fill: false, points: new Float64Array([0, 0, 1, 1]), bounds: [0, 0, 1, 1] },
  ],
  visibleLayers: new Set([0, 1]),
  opacity: 1,
  layerColors: ['#a', '#b'],
  ink: '#000',
  paper: null,
  crop: null,
};

const routePreview = {
  layers: ['M-OV-T1', 'M-NODE'],
  paths: [
    { layer: 0, closed: false, fill: false, points: [0, 0, 1000, 0] },
    { layer: 1, closed: true, fill: false, points: [0, 0, 10, 0, 10, 10, 0, 0] },
  ],
} as unknown as CadPreviewRead;

const colors = { 'M-OV-T1': '#red', 'M-NODE': '#grey' };

describe('mergeRoutePaint', () => {
  it('без трасс рисуется только вид родителя', () => {
    expect(mergeRoutePaint(base, 2, null, frame, page, '#ink')).toBe(base);
    expect(mergeRoutePaint(null, 0, null, frame, page, '#ink')).toBeNull();
  });

  it('слои трасс идут после слоёв родителя, цвета - по именам слоёв', () => {
    const merged = mergeRoutePaint(base, 2, { preview: routePreview, colors, hiddenMask: 0 }, frame, page, '#ink');
    expect(merged?.paths).toHaveLength(3);
    expect(merged?.paths.map((path) => path.layer)).toEqual([0, 2, 3]);
    expect(merged?.layerColors).toEqual(['#a', '#b', '#red', '#grey']);
    expect([...(merged?.visibleLayers ?? [])].sort()).toEqual([0, 1, 2, 3]);
  });

  it('скрытый человеком слой трасс не рисуется, слои родителя не затронуты', () => {
    const hiddenMask = withMepLayersHidden(0, ['M-NODE'], true);
    const merged = mergeRoutePaint(base, 2, { preview: routePreview, colors, hiddenMask }, frame, page, '#ink');
    expect(merged?.visibleLayers.has(2)).toBe(true);
    expect(merged?.visibleLayers.has(3)).toBe(false);
    expect(merged?.visibleLayers.has(0)).toBe(true);
  });

  it('координаты трасс переводятся тем же кадром, что и DXF вида', () => {
    const merged = mergeRoutePaint(null, 0, { preview: routePreview, colors, hiddenMask: 0 }, frame, page, '#ink');
    // 1000 мм = 100 pt при 10 мм/pt; origin по Y = 100 pt от верха: y = 100/100 = 1.
    const first = merged?.paths[0];
    expect(first?.layer).toBe(0);
    expect(Array.from(first?.points ?? [])).toEqual([0, 1, 0.5, 1]);
  });

  it('нет кадра или листа - трассы не рисуются', () => {
    const input = { preview: routePreview, colors, hiddenMask: 0 };
    expect(mergeRoutePaint(base, 2, input, null, page, '#ink')).toBe(base);
    expect(mergeRoutePaint(base, 2, input, frame, null, '#ink')).toBe(base);
  });
});

describe('route-задания в списках', () => {
  it('подпись: лист с 1 и вид', () => {
    expect(routeJobLabel({ page_index: 80, view: 1 })).toBe('Трассы механики · лист 81, вид 1');
    expect(routeJobLabel({ page_index: null, view: null })).toBe('Трассы механики');
    expect(isRouteJob({ job_type: 'cad_mep_route' })).toBe(true);
    expect(isRouteJob({ job_type: 'cad_pdf_convert' })).toBe(false);
  });

  it('трассы не заменяют итог преобразования листа', () => {
    const results = latestSheetJobs([
      {
        job_id: 'route',
        job_type: 'cad_mep_route',
        status: 'failed',
        result_status: null,
        requested_pages: [3],
        created_at: '2026-11-10T12:00:00Z',
      },
      {
        job_id: 'convert',
        job_type: 'cad_pdf_convert',
        status: 'succeeded',
        result_status: 'completed_requires_review',
        requested_pages: [3],
        created_at: '2026-11-10T10:00:00Z',
      },
    ]);
    expect(results.get(3)?.jobId).toBe('convert');
    expect(results.get(3)?.kind).toBe('recognized');
  });
});
