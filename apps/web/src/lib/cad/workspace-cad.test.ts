import { describe, expect, it } from 'vitest';

import { diagnostics, FRAME_NO, FRAME_OK, JOB_ID, preview } from '@/components/cad/viewer/fixtures';

import { frameOf } from './frame';
import {
  WORKSPACE_CAD_OPACITY,
  WORKSPACE_DRAFT_ID,
  cadPageHref,
  isReadableJob,
  matchingPreview,
  overlayAvailability,
  overlayPaintData,
  pickWorkspaceView,
  withCadTab,
  workspaceMarks,
  workspaceViewParams,
} from './workspace-cad';

const pages = (views: Record<number, number[]>) => ({
  pages: Object.entries(views).map(([index, list]) => ({
    index: Number(index),
    legacy_pdf_page: Number(index) + 1,
    views: list.map((view) => ({ view })),
  })),
});

const asJob = (value: unknown) => value as Parameters<typeof pickWorkspaceView>[0];

describe('вид листа в рабочей области', () => {
  it('нет выбора - первый вид листа, виды по возрастанию', () => {
    const job = asJob(pages({ 3: [2, 1, 4], 5: [1] }));
    expect(pickWorkspaceView(job, 3, null)).toEqual({ views: [1, 2, 4], view: 1 });
  });

  it('выбранный вид, которого у листа нет, заменяется первым', () => {
    const job = asJob(pages({ 3: [1, 2] }));
    expect(pickWorkspaceView(job, 3, 2).view).toBe(2);
    expect(pickWorkspaceView(job, 3, 9).view).toBe(1);
  });

  it('листа нет в задании - видов нет', () => {
    expect(pickWorkspaceView(asJob(pages({ 0: [1] })), 7, null)).toEqual({
      views: [],
      view: null,
    });
  });

  it('читать можно только выпущенный итог попытки-результата', () => {
    expect(isReadableJob({ result_attempt: 1, result_status: 'completed_requires_review' })).toBe(
      true,
    );
    expect(isReadableJob({ result_attempt: 1, result_status: 'no_cad_review_required' })).toBe(
      true,
    );
    expect(isReadableJob({ result_attempt: 1, result_status: 'failed' })).toBe(false);
    expect(
      isReadableJob({ result_attempt: null, result_status: 'completed_requires_review' }),
    ).toBe(false);
  });

  it('параметры запросов: попытка-результат, страница и вид; без вида или итога - null', () => {
    const ready = { job_id: JOB_ID, result_attempt: 2, result_status: 'completed_requires_review' };
    expect(workspaceViewParams('p', 'r', ready, 4, 3)).toEqual({
      projectId: 'p',
      revisionId: 'r',
      jobId: JOB_ID,
      attempt: 2,
      pageIndex: 4,
      view: 3,
    });
    expect(workspaceViewParams('p', 'r', ready, 4, null)).toBeNull();
    expect(workspaceViewParams('p', 'r', { ...ready, result_status: 'failed' }, 4, 1)).toBeNull();
  });
});

describe('наложение DXF', () => {
  it('предпросмотр другого DXF не принимается', () => {
    const diag = diagnostics();
    expect(matchingPreview(diag, preview())).not.toBeNull();
    expect(matchingPreview(diag, preview({ dxf_sha256: 'c'.repeat(64) }))).toBeNull();
    expect(matchingPreview(diag, undefined)).toBeNull();
  });

  it('доступно при подтверждённом кадре; без DXF-предпросмотра и без кадра - нет, с причиной', () => {
    const frame = frameOf(FRAME_OK);
    expect(overlayAvailability(diagnostics(), preview(), frame)).toEqual({
      available: true,
      reason: null,
    });
    // предпросмотр ещё не пришёл - наложение не закрывается
    expect(overlayAvailability(diagnostics(), null, null).available).toBe(true);

    const noPreview = overlayAvailability(diagnostics({ preview_available: false }), null, null);
    expect(noPreview.available).toBe(false);
    expect(noPreview.reason).toContain('Предпросмотра DXF нет');

    const noFrame = overlayAvailability(diagnostics({ frame: FRAME_NO }), preview(), null);
    expect(noFrame.available).toBe(false);
    expect(noFrame.reason).toContain('Кадр координат не подтверждён');

    // кадр подтверждён, но не собирается (нет единиц) - тоже нет
    expect(overlayAvailability(diagnostics(), preview(), null).available).toBe(false);
  });

  it('данные слоя: слои получают цвета палитры по порядку', () => {
    const frame = frameOf(FRAME_OK);
    const data = overlayPaintData(preview(), frame, { width: 842, height: 595 }, 'ink', [
      'c1',
      'c2',
      'c3',
    ]);
    // в предпросмотре два слоя
    expect(data?.layerColors).toEqual(['c1', 'c2']);
  });

  it('данные слоя: пути в долях листа, все слои видны, без бумаги и контекста', () => {
    const frame = frameOf(FRAME_OK);
    const data = overlayPaintData(preview(), frame, { width: 842, height: 595 }, 'ink');
    expect(data).not.toBeNull();
    expect(data?.paths).toHaveLength(2);
    expect([...(data?.visibleLayers ?? [])]).toEqual([0, 1]);
    expect(data?.opacity).toBe(WORKSPACE_CAD_OPACITY);
    expect(data?.paper).toBeNull();
    expect(data?.crop).toBeNull();
    expect(data?.ink).toBe('ink');
    // без палитры слои красятся чернилами
    expect(data?.layerColors).toEqual([]);
    // начало DXF (0, 0) лежит в origin_pt кадра, нормализованном размером листа
    const first = data?.paths[0]?.points;
    expect(first?.[0]).toBeCloseTo(37.5 / 842, 9);
    expect(first?.[1]).toBeCloseTo(700 / 595, 9);
  });

  it('нет предпросмотра, кадра или размера листа - слоя нет', () => {
    const frame = frameOf(FRAME_OK);
    const page = { width: 842, height: 595 };
    expect(overlayPaintData(null, frame, page, 'i')).toBeNull();
    expect(overlayPaintData(preview(), null, page, 'i')).toBeNull();
    expect(overlayPaintData(preview(), frame, null, 'i')).toBeNull();
  });
});

describe('отметки замечаний', () => {
  const page = { width: 1000, height: 500 };

  it('рамки в долях листа, номера по порядку; черновик - следующим номером', () => {
    const marks = workspaceMarks(
      [{ id: 'a', status: 'open', bbox_pt: [100, 50, 300, 250] }],
      [500, 100, 700, 200],
      page,
    );
    expect(marks).toEqual([
      { id: 'a', number: 1, status: 'open', rect: [0.1, 0.1, 0.3, 0.5] },
      { id: WORKSPACE_DRAFT_ID, number: 2, status: 'open', rect: [0.5, 0.2, 0.7, 0.4] },
    ]);
  });

  it('размер листа неизвестен - отметок нет', () => {
    expect(
      workspaceMarks([{ id: 'a', status: 'open', bbox_pt: [1, 1, 5, 5] }], null, null),
    ).toEqual([]);
  });
});

describe('ссылки', () => {
  it('без задания - страница CAD ревизии', () => {
    expect(cadPageHref('p1', 'r1', null)).toBe('/projects/p1/cad?revision=r1');
  });

  it('задание без листа (идёт или ошибка) - только задание', () => {
    expect(cadPageHref('p1', 'r1', { jobId: JOB_ID, page: null, view: null })).toBe(
      `/projects/p1/cad?revision=r1&job=${JOB_ID}`,
    );
  });

  it('распознанный лист - задание, страница и вид', () => {
    expect(cadPageHref('p1', 'r1', { jobId: JOB_ID, page: 2, view: 3 })).toBe(
      `/projects/p1/cad?revision=r1&job=${JOB_ID}&page=2&view=3`,
    );
  });

  it('вкладка CAD в адресе рабочей области', () => {
    expect(withCadTab('/projects/p/workspace?revision=r&page=2')).toBe(
      '/projects/p/workspace?revision=r&page=2&tab=cad',
    );
  });
});
