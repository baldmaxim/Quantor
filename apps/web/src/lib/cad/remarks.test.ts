import { describe, expect, it } from 'vitest';

import {
  REMARKS_COORDINATE_SYSTEM,
  REMARKS_SCHEMA,
  MAX_COMMENT_LENGTH,
  MAX_REMARKS_PER_FILE,
  bboxPtToNormalized,
  buildRemarksFile,
  cameraForBbox,
  importSummary,
  isValidBboxPt,
  newRemarkId,
  normalizeBboxPt,
  parseRemarksFile,
  remarksCounter,
  remarksFilename,
  screenToPagePt,
  sortRemarks,
  toImportBody,
  type IRemark,
  type IRemarkBinding,
} from './remarks';

const PAGE = { width: 1000, height: 800 };

const BINDING: IRemarkBinding = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'j1',
  attempt: 2,
  pageIndex: 3,
  legacyPdfPage: 4,
  view: 1,
  dxfSha256: 'a'.repeat(64),
};

const remark = (patch: Partial<IRemark> = {}): IRemark => ({
  id: 'id-1',
  type: 'missing_wall',
  comment: 'Нет стены в осях А-Б',
  reviewer: 'Иванов',
  status: 'open',
  bbox_pt: [10, 20, 110, 220],
  created_at: '2026-11-09T10:00:00.000Z',
  updated_at: '2026-11-09T10:00:00.000Z',
  ...patch,
});

const fileOf = (patch: Record<string, unknown> = {}, remarks: IRemark[] = [remark()]): string =>
  JSON.stringify({ ...buildRemarksFile(BINDING, 'Иванов', remarks, new Date()), ...patch });

describe('привязка и имена', () => {
  it('имя файла: страница PDF, вид и местное время до минуты', () => {
    const at = new Date(2026, 10, 9, 7, 5);
    expect(remarksFilename(BINDING, at)).toBe('Замечания_стр4_вид1_20261109-0705.json');
  });

  it('идентификаторы уникальны', () => {
    expect(newRemarkId()).not.toBe(newRemarkId());
    expect(newRemarkId()).toMatch(/^[0-9a-f-]{36}$/);
  });
});

describe('координаты', () => {
  it('углы в любом порядке дают x0<x1, y0<y1 и ограничиваются страницей', () => {
    expect(normalizeBboxPt([300, 200], [100, 50], PAGE)).toEqual([100, 50, 300, 200]);
    expect(normalizeBboxPt([-40, -10], [1200, 900], PAGE)).toEqual([0, 0, 1000, 800]);
  });

  it('слишком малый и вырожденный прямоугольник отбрасывается', () => {
    expect(normalizeBboxPt([10, 10], [10.5, 300], PAGE)).toBeNull();
    expect(normalizeBboxPt([10, 10], [Number.NaN, 300], PAGE)).toBeNull();
    expect(normalizeBboxPt([2000, 2000], [3000, 3000], PAGE)).toBeNull();
  });

  it('экран -> pt с учётом смещения и масштаба камеры', () => {
    const camera = { scale: 2, offsetX: 50, offsetY: 10 };
    expect(screenToPagePt(camera, 150, 110)).toEqual([50, 50]);
  });

  it('pt -> доли листа', () => {
    expect(bboxPtToNormalized([100, 80, 500, 400], PAGE)).toEqual([0.1, 0.1, 0.5, 0.5]);
  });

  it('проверка прямоугольника: порядок, знак, границы страницы', () => {
    expect(isValidBboxPt([1, 1, 5, 5], PAGE)).toBe(true);
    expect(isValidBboxPt([5, 1, 1, 5], PAGE)).toBe(false);
    expect(isValidBboxPt([-1, 1, 5, 5], PAGE)).toBe(false);
    expect(isValidBboxPt([1, 1, 5, 801], PAGE)).toBe(false);
    expect(isValidBboxPt([1, 1, 5, 801], null)).toBe(true);
    expect(isValidBboxPt([1, 1, 5], PAGE)).toBe(false);
  });

  it('«К участку»: участок по центру и целиком', () => {
    const view = { width: 800, height: 600 };
    const camera = cameraForBbox([100, 100, 300, 200], view);
    expect(camera).not.toBeNull();
    if (!camera) return;
    const [x, y] = [(200 * camera.scale + camera.offsetX), (150 * camera.scale + camera.offsetY)];
    expect(x).toBeCloseTo(400, 6);
    expect(y).toBeCloseTo(300, 6);
    expect(200 * camera.scale).toBeLessThanOrEqual(800);
    expect(cameraForBbox([1, 1, 1, 5], view)).toBeNull();
    expect(cameraForBbox([1, 1, 5, 5], { width: 0, height: 100 })).toBeNull();
  });
});

describe('порядок и счётчик', () => {
  it('итог импорта по ответу сервера', () => {
    expect(importSummary({ imported: 2, updated: 1 })).toBe('Импортировано: 2, обновлено: 1');
  });

  it('порядок номеров - по времени создания', () => {
    const sorted = sortRemarks([
      remark({ id: 'z', created_at: '2026-11-09T11:00:00.000Z' }),
      remark({ id: 'y', created_at: '2026-11-09T09:00:00.000Z' }),
    ]);
    expect(sorted.map((item) => item.id)).toEqual(['y', 'z']);
  });

  it('счётчик «открыто N / всего M»', () => {
    expect(
      remarksCounter([remark(), remark({ id: 'b', status: 'resolved' }), remark({ id: 'c' })]),
    ).toBe('открыто 2 / всего 3');
  });
});

describe('файл замечаний', () => {
  it('выгрузка имеет схему, привязку, систему координат и приёмку=false', () => {
    const file = buildRemarksFile(BINDING, ' Иванов ', [remark()], new Date('2026-11-09T10:00:00Z'));
    expect(file).toMatchObject({
      schema: REMARKS_SCHEMA,
      project_id: 'p1',
      revision_id: 'r1',
      job_id: 'j1',
      attempt: 2,
      page_index: 3,
      legacy_pdf_page: 4,
      view: 1,
      dxf_sha256: 'a'.repeat(64),
      coordinate_system: REMARKS_COORDINATE_SYSTEM,
      exported_at: '2026-11-09T10:00:00.000Z',
      reviewer: 'Иванов',
      engineering_acceptance: false,
    });
    expect(file.remarks).toHaveLength(1);
  });

  it('свой файл разбирается обратно без потерь', () => {
    const result = parseRemarksFile(fileOf(), BINDING, PAGE);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.remarks).toEqual([remark()]);
      expect(result.reviewer).toBe('Иванов');
    }
  });

  it.each([
    ['ревизия', { revision_id: 'x' }],
    ['задание', { job_id: 'x' }],
    ['попытка', { attempt: 9 }],
    ['страница', { page_index: 0 }],
    ['страница', { legacy_pdf_page: 9 }],
    ['вид', { view: 2 }],
    ['DXF (sha256)', { dxf_sha256: 'b'.repeat(64) }],
    ['DXF (sha256)', { dxf_sha256: null }],
  ])('несовпадение привязки (%s) отклоняет файл', (what, patch) => {
    const result = parseRemarksFile(fileOf(patch), BINDING, PAGE);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain(what);
  });

  it('другая схема, не JSON, лишний тип и длинный комментарий отклоняются с причиной', () => {
    expect(parseRemarksFile('{', BINDING, PAGE)).toMatchObject({ ok: false });
    const schema = parseRemarksFile(fileOf({ schema: 'other.v9' }), BINDING, PAGE);
    expect(schema.ok).toBe(false);
    if (!schema.ok) expect(schema.reason).toContain('схема');
    const type = parseRemarksFile(
      fileOf({}, [remark({ type: 'bogus' as IRemark['type'] })]),
      BINDING,
      PAGE,
    );
    expect(type.ok).toBe(false);
    const long = parseRemarksFile(
      fileOf({}, [remark({ comment: 'я'.repeat(MAX_COMMENT_LENGTH + 1) })]),
      BINDING,
      PAGE,
    );
    expect(long.ok).toBe(false);
  });

  it('приёмка true в файле отклоняется', () => {
    expect(parseRemarksFile(fileOf({ engineering_acceptance: true }), BINDING, PAGE).ok).toBe(false);
  });

  it('некорректный участок отклоняет файл', () => {
    const bad = parseRemarksFile(
      fileOf({}, [remark({ bbox_pt: [100, 20, 10, 220] })]),
      BINDING,
      PAGE,
    );
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.reason).toContain('участок');
    const outside = parseRemarksFile(
      fileOf({}, [remark({ bbox_pt: [10, 20, 5000, 220] })]),
      BINDING,
      PAGE,
    );
    expect(outside.ok).toBe(false);
  });
});

describe('импорт на сервер', () => {
  it('файл обмена переводится в тело запроса без потерь', () => {
    const file = buildRemarksFile(BINDING, 'Иванов', [remark()], new Date('2026-11-09T12:00:00Z'));
    const body = toImportBody(file);
    expect(body).toMatchObject({
      schema: REMARKS_SCHEMA,
      project_id: 'p1',
      revision_id: 'r1',
      job_id: 'j1',
      attempt: 2,
      page_index: 3,
      legacy_pdf_page: 4,
      view: 1,
      coordinate_system: REMARKS_COORDINATE_SYSTEM,
      exported_at: '2026-11-09T12:00:00.000Z',
      reviewer: 'Иванов',
      engineering_acceptance: false,
    });
    expect(body.dxf_sha256).toBe('a'.repeat(64));
    expect(body.remarks).toEqual([remark()]);
    expect(JSON.parse(JSON.stringify(body))).toEqual(body);
  });

  it('больше 500 замечаний в файле отклоняется до отправки', () => {
    const many = Array.from({ length: MAX_REMARKS_PER_FILE + 1 }, (_, index) =>
      remark({ id: `id-${index}` }),
    );
    const result = parseRemarksFile(fileOf({}, many), BINDING, PAGE);
    expect(result.ok).toBe(false);
  });

  it('файл прежней выгрузки (до серверного хранения) разбирается как раньше', () => {
    const legacy = JSON.stringify({
      schema: 'quantor.cad-remarks.v1',
      project_id: 'p1',
      revision_id: 'r1',
      job_id: 'j1',
      attempt: 2,
      page_index: 3,
      legacy_pdf_page: 4,
      view: 1,
      dxf_sha256: 'a'.repeat(64),
      coordinate_system: 'pdf_pt_top_left',
      exported_at: '2026-11-09T09:00:00.000Z',
      reviewer: 'Иванов',
      engineering_acceptance: false,
      remarks: [remark()],
    });
    const result = parseRemarksFile(legacy, BINDING, PAGE);
    expect(result.ok && result.remarks.map((item) => item.id)).toEqual(['id-1']);
  });
});
