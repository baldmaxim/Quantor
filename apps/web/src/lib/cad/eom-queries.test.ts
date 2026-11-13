import type { CadPreviewRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { eomMark, withEomPreview } from './eom-queries';

const preview = (layers: string[], paths: CadPreviewRead['paths']): CadPreviewRead =>
  ({
    job_id: 'j',
    attempt: 1,
    page_index: 0,
    view: 1,
    units: 'mm',
    dxf_sha256: 'x',
    layers,
    paths,
    point_count: paths.reduce((sum, path) => sum + path.points.length / 2, 0),
    truncated: false,
    flatten_mm: 0,
    bbox: null,
    frame: {} as CadPreviewRead['frame'],
  }) as CadPreviewRead;

describe('ЭОМ и СС на листе', () => {
  it('слои ЭОМ дописываются после слоёв механики, индексы путей сдвигаются', () => {
    const mep = preview(['M-VK-V1', 'M-OV-T1'], [
      { layer: 1, closed: false, fill: false, points: [0, 0, 10, 0] },
    ]);
    const eom = preview(['E-EO-FEED', 'E-EO-DEV'], [
      { layer: 0, closed: false, fill: false, points: [0, 0, 5, 0] },
      { layer: 1, closed: true, fill: false, points: [0, 0, 1, 0, 1, 1, 0, 0] },
    ]);
    const merged = withEomPreview(mep, eom);
    expect(merged?.layers).toEqual(['M-VK-V1', 'M-OV-T1', 'E-EO-FEED', 'E-EO-DEV']);
    expect(merged?.paths.map((path) => path.layer)).toEqual([1, 2, 3]);
    expect(merged?.point_count).toBe(2 + 2 + 4);
    expect(merged?.job_id).toBe('j');
  });

  it('без одной из частей - вторая как есть', () => {
    const eom = preview(['E-SS-TRAY'], [{ layer: 0, closed: false, fill: false, points: [0, 0, 1, 1] }]);
    expect(withEomPreview(null, eom)).toBe(eom);
    expect(withEomPreview(eom, null)).toBe(eom);
    expect(withEomPreview(null, null)).toBeNull();
  });

  it('отметка кэша - только у успешного задания', () => {
    expect(eomMark(null)).toBe('none');
    expect(
      eomMark({ job_id: 'a', status: 'running', finished_at: null } as Parameters<typeof eomMark>[0]),
    ).toBe('none');
    expect(
      eomMark({ job_id: 'a', status: 'succeeded', finished_at: 't' } as Parameters<typeof eomMark>[0]),
    ).toBe('a:t');
  });
});
