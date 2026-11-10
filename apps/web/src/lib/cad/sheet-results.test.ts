import { describe, expect, it } from 'vitest';

import { latestSheetJobs } from './sheet-results';

const job = (patch: Record<string, unknown>) =>
  ({
    job_id: 'j',
    status: 'succeeded',
    result_status: 'completed_requires_review',
    requested_pages: [0],
    created_at: '2026-11-10T10:00:00Z',
    ...patch,
  }) as unknown as Parameters<typeof latestSheetJobs>[0][number];

describe('последний результат листа', () => {
  it('нет заданий или нет страниц - пустая карта', () => {
    expect(latestSheetJobs([]).size).toBe(0);
    expect(latestSheetJobs([job({ requested_pages: null })]).size).toBe(0);
    expect(latestSheetJobs([job({ requested_pages: [] })]).size).toBe(0);
  });

  it('распознан: оба выпускаемых итога', () => {
    const map = latestSheetJobs([
      job({ job_id: 'a', requested_pages: [0] }),
      job({ job_id: 'b', requested_pages: [1], result_status: 'no_cad_review_required' }),
    ]);
    expect(map.get(0)).toEqual({ jobId: 'a', kind: 'recognized', view: null, dxf: true });
    expect(map.get(1)).toEqual({ jobId: 'b', kind: 'recognized', view: null, dxf: false });
  });

  it('идущее задание - running, даже если у него есть итог прежней попытки', () => {
    const map = latestSheetJobs([
      job({ job_id: 'q', status: 'queued', result_status: null }),
      job({ job_id: 'r', status: 'running', result_status: 'failed', requested_pages: [1] }),
    ]);
    expect(map.get(0)?.kind).toBe('running');
    expect(map.get(1)?.kind).toBe('running');
  });

  it('отказ, ошибка и отмена - failed', () => {
    const map = latestSheetJobs([
      job({ job_id: 'a', status: 'failed', result_status: null, requested_pages: [0] }),
      job({ job_id: 'b', status: 'cancelled', result_status: null, requested_pages: [1] }),
      job({ job_id: 'c', result_status: 'failed', requested_pages: [2] }),
    ]);
    expect([0, 1, 2].map((page) => map.get(page)?.kind)).toEqual(['failed', 'failed', 'failed']);
  });

  it('страница в двух заданиях: берётся новее, независимо от порядка в списке', () => {
    const older = job({ job_id: 'old', created_at: '2026-11-09T10:00:00Z' });
    const newer = job({
      job_id: 'new',
      created_at: '2026-11-10T12:00:00Z',
      status: 'failed',
      result_status: null,
    });
    expect(latestSheetJobs([older, newer]).get(0)).toMatchObject({ jobId: 'new', kind: 'failed' });
    expect(latestSheetJobs([newer, older]).get(0)).toMatchObject({ jobId: 'new', kind: 'failed' });
  });

  it('новое задание не затрагивает листы, которых в нём нет', () => {
    const map = latestSheetJobs([
      job({ job_id: 'old', requested_pages: [0, 1], created_at: '2026-11-09T10:00:00Z' }),
      job({ job_id: 'new', requested_pages: [1], created_at: '2026-11-10T10:00:00Z' }),
    ]);
    expect(map.get(0)?.jobId).toBe('old');
    expect(map.get(1)?.jobId).toBe('new');
  });

  it('завершено без понятного итога - листа в карте нет', () => {
    expect(latestSheetJobs([job({ result_status: null })]).size).toBe(0);
  });
});
