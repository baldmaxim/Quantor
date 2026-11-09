/**
 * Замечания проверяющего к виду результата CAD: модель, привязка, координаты, слияние и обмен JSON.
 *
 * Координаты замечания - точки исходного PDF от левого верхнего угла страницы
 * (`pdf_pt_top_left`), те же единицы, в которых отрисовщик отдаёт размер листа при масштабе 1
 * (ADR-0008); нормализованные доли листа получаются делением на размер страницы. Замечание - след
 * человека, а не измерение и не приёмка: в расчёт оно не входит (`engineering_acceptance: false`).
 *
 * Замечания хранятся на сервере (таблица `cad_remarks`); здесь - только модель, координаты, файл
 * обмена `quantor.cad-remarks.v1` и его предварительная проверка. Слияние при импорте делает сервер.
 *
 * Модуль без DOM и без React: ошибка здесь - «отметка уехала с места» или «чужие замечания
 * подмешались к другому виду», и ловить её нужно тестами.
 */

import type { CadRemarksFile } from '@quantor/api-client';
import { z } from 'zod';

import { MAX_SCALE, MIN_SCALE, type CameraState, type Viewport } from '@/lib/viewer/camera';
import { clamp, type NormalizedRect } from '@/lib/viewer/coordinates';

export const REMARKS_SCHEMA = 'quantor.cad-remarks.v1';
export const REMARKS_COORDINATE_SYSTEM = 'pdf_pt_top_left';

/** Предел длины комментария. */
export const MAX_COMMENT_LENGTH = 2000;
/** Предел числа замечаний в файле обмена (тот же, что на сервере). */
export const MAX_REMARKS_PER_FILE = 500;
/** Предел размера файла импорта, байт. */
export const MAX_IMPORT_BYTES = 2 * 1024 * 1024;
/** Предел длины имени проверяющего. */
export const MAX_REVIEWER_LENGTH = 120;
/** Наименьшая сторона отметки, pt: меньший прямоугольник - случайный клик, а не участок. */
export const MIN_BOX_PT = 2;

export const REMARK_TYPES = [
  { value: 'missing_wall', label: 'Нет стены' },
  { value: 'false_wall', label: 'Лишняя стена' },
  { value: 'missing_door', label: 'Нет двери' },
  { value: 'door_geometry', label: 'Геометрия двери' },
  { value: 'missing_gate', label: 'Нет ворот' },
  { value: 'missing_glazing', label: 'Нет остекления' },
  { value: 'monolith', label: 'Монолит' },
  { value: 'room_boundary', label: 'Граница помещения' },
  { value: 'wrong_class', label: 'Неверный класс' },
  { value: 'other', label: 'Другое' },
] as const;

export type RemarkType = (typeof REMARK_TYPES)[number]['value'];
export type RemarkStatus = 'open' | 'resolved';

export const REMARK_STATUS_LABELS: Readonly<Record<RemarkStatus, string>> = {
  open: 'Нужно перепроверить',
  resolved: 'Проверено: исправлено',
};

const TYPE_VALUES = REMARK_TYPES.map((item) => item.value) as [RemarkType, ...RemarkType[]];

export const remarkTypeLabel = (type: RemarkType): string =>
  REMARK_TYPES.find((item) => item.value === type)?.label ?? type;

/** Прямоугольник в pt PDF: [x0, y0, x1, y1], x0 < x1, y0 < y1. */
export type BboxPt = readonly [number, number, number, number];

export interface IPageSizePt {
  readonly width: number;
  readonly height: number;
}

/** К чему привязаны замечания. Любое несовпадение - чужие замечания. */
export interface IRemarkBinding {
  readonly projectId: string;
  readonly revisionId: string;
  readonly jobId: string;
  readonly attempt: number;
  readonly pageIndex: number;
  readonly legacyPdfPage: number;
  readonly view: number;
  /** SHA-256 DXF вида; `null` - DXF нет. */
  readonly dxfSha256: string | null;
}

export interface IRemark {
  readonly id: string;
  readonly type: RemarkType;
  readonly comment: string;
  readonly reviewer: string;
  readonly status: RemarkStatus;
  readonly bbox_pt: BboxPt;
  readonly created_at: string;
  readonly updated_at: string;
}

// ---------------------------------------------------------------- ключи и имена

/** Ключ, под которым браузер помнит имя проверяющего. */
export const REVIEWER_STORAGE_KEY = 'quantor.cad-remarks.reviewer.v1';

const pad = (value: number): string => String(value).padStart(2, '0');

/** `Замечания_стр{legacy_pdf_page}_вид{view}_{yyyyMMdd-HHmm}.json` по местному времени. */
export const remarksFilename = (binding: IRemarkBinding, at: Date): string =>
  `Замечания_стр${binding.legacyPdfPage}_вид${binding.view}_` +
  `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}-${pad(at.getHours())}${pad(at.getMinutes())}.json`;

/** UUID v4; `randomUUID` есть только в безопасном контексте, поэтому запасной путь. */
export const newRemarkId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

// ---------------------------------------------------------------- координаты

/** Точка экрана (px области просмотра) -> точка листа в pt при данной камере. */
export const screenToPagePt = (camera: CameraState, x: number, y: number): [number, number] => [
  (x - camera.offsetX) / camera.scale,
  (y - camera.offsetY) / camera.scale,
];

/**
 * Две угловые точки (pt) -> прямоугольник отметки: порядок углов любой, края ограничены
 * страницей. Слишком малый или вырожденный прямоугольник - `null`.
 */
export const normalizeBboxPt = (
  a: readonly [number, number],
  b: readonly [number, number],
  page: IPageSizePt,
): BboxPt | null => {
  if (![a[0], a[1], b[0], b[1], page.width, page.height].every(Number.isFinite)) return null;
  if (page.width <= 0 || page.height <= 0) return null;
  const x0 = clamp(Math.min(a[0], b[0]), 0, page.width);
  const x1 = clamp(Math.max(a[0], b[0]), 0, page.width);
  const y0 = clamp(Math.min(a[1], b[1]), 0, page.height);
  const y1 = clamp(Math.max(a[1], b[1]), 0, page.height);
  return x1 - x0 >= MIN_BOX_PT && y1 - y0 >= MIN_BOX_PT ? [x0, y0, x1, y1] : null;
};

/** Допуск на ошибки округления при проверке «внутри страницы», pt. */
const PAGE_EPSILON_PT = 0.5;

/** Прямоугольник годен: конечные числа, x0 < x1, y0 < y1, неотрицательный и (если страница известна) внутри неё. */
export const isValidBboxPt = (
  bbox: readonly number[],
  page: IPageSizePt | null,
): bbox is BboxPt => {
  if (bbox.length !== 4 || !bbox.every(Number.isFinite)) return false;
  const [x0, y0, x1, y1] = bbox as unknown as BboxPt;
  if (x0 < 0 || y0 < 0 || !(x0 < x1) || !(y0 < y1)) return false;
  if (page && (x1 > page.width + PAGE_EPSILON_PT || y1 > page.height + PAGE_EPSILON_PT))
    return false;
  return true;
};

/** pt PDF -> нормализованные доли листа. */
export const bboxPtToNormalized = (bbox: BboxPt, page: IPageSizePt): NormalizedRect => [
  bbox[0] / page.width,
  bbox[1] / page.height,
  bbox[2] / page.width,
  bbox[3] / page.height,
];

/** Поля вокруг участка при «К участку», px. */
const FOCUS_PADDING_PX = 32;
/** Наибольший масштаб при «К участку»: маленький участок не растягивается в пиксели. */
const FOCUS_MAX_SCALE = 8;

/** Камера, на которой участок виден целиком и по центру. Состояние для `Camera.set`. */
export const cameraForBbox = (bbox: BboxPt, viewport: Viewport): CameraState | null => {
  if (viewport.width <= 0 || viewport.height <= 0) return null;
  const width = bbox[2] - bbox[0];
  const height = bbox[3] - bbox[1];
  if (!(width > 0) || !(height > 0)) return null;
  const scale = clamp(
    Math.min(
      (viewport.width - FOCUS_PADDING_PX * 2) / width,
      (viewport.height - FOCUS_PADDING_PX * 2) / height,
    ),
    MIN_SCALE,
    Math.min(MAX_SCALE, FOCUS_MAX_SCALE),
  );
  return {
    scale,
    offsetX: viewport.width / 2 - ((bbox[0] + bbox[2]) / 2) * scale,
    offsetY: viewport.height / 2 - ((bbox[1] + bbox[3]) / 2) * scale,
  };
};

// ---------------------------------------------------------------- схема

const isoString = z
  .string()
  .refine((value) => Number.isFinite(Date.parse(value)), 'Некорректная дата.');

const remarkSchema = z.object({
  id: z.string().min(1).max(64),
  type: z.enum(TYPE_VALUES),
  comment: z.string().max(MAX_COMMENT_LENGTH),
  reviewer: z.string().max(MAX_REVIEWER_LENGTH).default(''),
  status: z.enum(['open', 'resolved']),
  bbox_pt: z.tuple([z.number(), z.number(), z.number(), z.number()]),
  created_at: isoString,
  updated_at: isoString,
});

const fileSchema = z.object({
  schema: z.literal(REMARKS_SCHEMA),
  project_id: z.string(),
  revision_id: z.string(),
  job_id: z.string(),
  attempt: z.number().int(),
  page_index: z.number().int(),
  legacy_pdf_page: z.number().int(),
  view: z.number().int(),
  dxf_sha256: z.string().nullable(),
  coordinate_system: z.literal(REMARKS_COORDINATE_SYSTEM),
  exported_at: isoString,
  reviewer: z.string().max(MAX_REVIEWER_LENGTH),
  engineering_acceptance: z.literal(false),
  remarks: z.array(remarkSchema).max(MAX_REMARKS_PER_FILE),
});

export interface IRemarksFile {
  readonly schema: typeof REMARKS_SCHEMA;
  readonly project_id: string;
  readonly revision_id: string;
  readonly job_id: string;
  readonly attempt: number;
  readonly page_index: number;
  readonly legacy_pdf_page: number;
  readonly view: number;
  readonly dxf_sha256: string | null;
  readonly coordinate_system: typeof REMARKS_COORDINATE_SYSTEM;
  readonly exported_at: string;
  readonly reviewer: string;
  readonly engineering_acceptance: false;
  readonly remarks: readonly IRemark[];
}

export const buildRemarksFile = (
  binding: IRemarkBinding,
  reviewer: string,
  remarks: readonly IRemark[],
  at: Date,
): IRemarksFile => ({
  schema: REMARKS_SCHEMA,
  project_id: binding.projectId,
  revision_id: binding.revisionId,
  job_id: binding.jobId,
  attempt: binding.attempt,
  page_index: binding.pageIndex,
  legacy_pdf_page: binding.legacyPdfPage,
  view: binding.view,
  dxf_sha256: binding.dxfSha256,
  coordinate_system: REMARKS_COORDINATE_SYSTEM,
  exported_at: at.toISOString(),
  reviewer: reviewer.trim(),
  engineering_acceptance: false,
  remarks: sortRemarks(remarks),
});

/** Порядок и номера: по времени создания, при равенстве - по id. Один порядок для списка и листа. */
export const sortRemarks = <T extends Pick<IRemark, 'id' | 'created_at'>>(
  remarks: readonly T[],
): T[] =>
  [...remarks].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id.localeCompare(b.id),
  );

export type ParseResult =
  | { readonly ok: true; readonly remarks: IRemark[]; readonly reviewer: string }
  | { readonly ok: false; readonly reason: string };

const fail = (reason: string): ParseResult => ({ ok: false, reason });

/**
 * Разбор файла импорта. Любое несовпадение привязки отклоняет файл целиком: замечания другого
 * вида на этом листе означали бы отметки не на тех местах.
 */
export const parseRemarksFile = (
  text: string,
  binding: IRemarkBinding,
  page: IPageSizePt | null,
): ParseResult => {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return fail('Файл не является JSON.');
  }
  if (typeof raw === 'object' && raw !== null && 'schema' in raw && raw.schema !== REMARKS_SCHEMA) {
    return fail(`Неизвестная схема файла (ожидается ${REMARKS_SCHEMA}).`);
  }
  const parsed = fileSchema.safeParse(raw);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue && issue.path.length > 0 ? ` (${issue.path.join('.')})` : '';
    return fail(`Файл не соответствует формату замечаний${where}.`);
  }
  const file = parsed.data;

  const mismatches: string[] = [];
  if (file.revision_id !== binding.revisionId) mismatches.push('ревизия');
  if (file.job_id !== binding.jobId) mismatches.push('задание');
  if (file.attempt !== binding.attempt) mismatches.push('попытка');
  if (file.page_index !== binding.pageIndex || file.legacy_pdf_page !== binding.legacyPdfPage) {
    mismatches.push('страница');
  }
  if (file.view !== binding.view) mismatches.push('вид');
  if (file.dxf_sha256 !== binding.dxfSha256) mismatches.push('DXF (sha256)');
  if (mismatches.length > 0) {
    return fail(`Файл относится к другому результату: не совпадает ${mismatches.join(', ')}.`);
  }

  for (const remark of file.remarks) {
    if (!isValidBboxPt(remark.bbox_pt, page)) {
      return fail(
        `Некорректный участок у замечания ${remark.id}: нужны x0 < x1, y0 < y1 внутри страницы.`,
      );
    }
  }
  return { ok: true, remarks: file.remarks, reviewer: file.reviewer };
};

// ---------------------------------------------------------------- импорт

/** Файл обмена -> тело запроса импорта: типы запроса берутся из сгенерированного клиента. */
export const toImportBody = (file: IRemarksFile): CadRemarksFile => ({
  schema: file.schema,
  project_id: file.project_id,
  revision_id: file.revision_id,
  job_id: file.job_id,
  attempt: file.attempt,
  page_index: file.page_index,
  legacy_pdf_page: file.legacy_pdf_page,
  view: file.view,
  dxf_sha256: file.dxf_sha256,
  coordinate_system: file.coordinate_system,
  exported_at: file.exported_at,
  reviewer: file.reviewer,
  engineering_acceptance: false,
  remarks: file.remarks.map((remark) => ({
    id: remark.id,
    type: remark.type,
    comment: remark.comment,
    reviewer: remark.reviewer,
    status: remark.status,
    bbox_pt: [remark.bbox_pt[0], remark.bbox_pt[1], remark.bbox_pt[2], remark.bbox_pt[3]],
    created_at: remark.created_at,
    updated_at: remark.updated_at,
  })),
});

/** Итог импорта по ответу сервера. */
export const importSummary = (result: {
  readonly imported: number;
  readonly updated: number;
}): string => `Импортировано: ${result.imported}, обновлено: ${result.updated}`;

/** Счётчик «открыто N / всего M». */
export const remarksCounter = (remarks: readonly IRemark[]): string =>
  `открыто ${remarks.filter((remark) => remark.status === 'open').length} / всего ${remarks.length}`;
