import type {
  CadLevelsDocAnswerRead,
  SectionIssueRead,
  SectionLevelRead,
  SectionPageRead,
} from '@quantor/api-client';

import { extractCode, extractMessage } from '@/lib/errors';

import { cadErrorText } from './errors';

/**
 * Чистые правила вкладки «Разрезы» (режим CAD): отметка, высоты, группировка уровней по линии
 * разреза, сводка по статусам. Уровни и разметка приходят от генератора; клиент ничего не считает
 * и не определяет сам - только показывает и отправляет решение человека (принять/отклонить).
 */

type DocAnswerOrigin = Pick<CadLevelsDocAnswerRead, 'answer_source' | 'file_name' | 'page_index'>;

export type SectionLevelStatus = SectionLevelRead['status'];

/** Границы высоты в свету, которые принимает сервер (как в генераторе трасс). */
export const CLEAR_HEIGHT_MIN_MM = 1500;
export const CLEAR_HEIGHT_MAX_MM = 6000;

/** Предупреждение запуска трасс: принятые разрезы дают разные высоты для отметки этажа листа. */
export const SECTION_AMBIGUOUS_WARNING = 'section_level_ambiguous';

/** Предупреждения источника «ответ к документации» (сервер: WARNING_DOC_*). */
export const DOC_ANSWER_AMBIGUOUS_WARNING = 'doc_answer_ambiguous';
export const DOC_ANSWER_OUT_OF_RANGE_WARNING = 'doc_answer_out_of_range';
export const SECTION_FLOOR_ELEVATION_UNKNOWN_WARNING = 'section_floor_elevation_unknown';

const WARNING_TEXTS: Readonly<Record<string, string>> = {
  [SECTION_AMBIGUOUS_WARNING]:
    'Для отметки листа найдено несколько принятых уровней с разной высотой — уточните уровни на листе разреза.',
  [DOC_ANSWER_AMBIGUOUS_WARNING]:
    'Подтверждённые ответы к документации для этого листа расходятся — взята плита проекта / допущение.',
  [DOC_ANSWER_OUT_OF_RANGE_WARNING]:
    'Подтверждённый ответ к документации вне пределов трасс (высота в свету 1500–6000 мм, плита 100–600 мм) — не применён, взята плита проекта / допущение.',
  [SECTION_FLOOR_ELEVATION_UNKNOWN_WARNING]:
    'Отметка этажа листа неизвестна — принятые уровни разрезов не применены; укажите отметку вручную.',
};

/** Текст предупреждения запуска трасс; незнакомый код показывается как есть. */
export const sectionWarningText = (code: string): string => WARNING_TEXTS[code] ?? code;

/** Значения `levels_source` у задания трасс (сервер: RouteLevels.source). */
export const LEVELS_SOURCE_SECTION = 'section';
export const LEVELS_SOURCE_DOC_ANSWER = 'doc_answer';
export const LEVELS_SOURCE_PROJECT_SLAB = 'project_slab';

/** Происхождение ответа к документации: файл и страница либо «введено вручную». */
const docAnswerOrigin = (answer: DocAnswerOrigin | null | undefined): string => {
  if (answer == null) return '';
  if (answer.answer_source === 'manual') return ' (введено вручную)';
  if (!answer.file_name) return '';
  const page = answer.page_index == null ? '' : `, стр. ${answer.page_index + 1}`;
  return ` (${answer.file_name}${page})`;
};

/** Строка «откуда высота» у задания трасс: разрезы, документация, плита проекта или допущение. */
export const routeLevelsText = (job: {
  readonly levels_source?: string | null;
  readonly clear_height_mm?: number | null;
  readonly slab_thickness_mm?: number | null;
  readonly levels_doc_answer?: DocAnswerOrigin | null;
}): string => {
  if (job.levels_source === LEVELS_SOURCE_SECTION && job.clear_height_mm != null) {
    return `Высота в свету: ${job.clear_height_mm} мм — по разрезам`;
  }
  if (job.levels_source === LEVELS_SOURCE_DOC_ANSWER) {
    const origin = docAnswerOrigin(job.levels_doc_answer);
    if (job.clear_height_mm != null) {
      return `Высота в свету: ${job.clear_height_mm} мм — по ответу к документации${origin}`;
    }
    if (job.slab_thickness_mm != null) {
      return `Плита ${job.slab_thickness_mm} мм — по ответу к документации${origin}`;
    }
  }
  if (job.levels_source === LEVELS_SOURCE_PROJECT_SLAB && job.slab_thickness_mm != null) {
    return `Плита ${job.slab_thickness_mm} мм — из уровней проекта`;
  }
  return 'Высота: допущение движка';
};

const STATUS_LABELS: Readonly<Record<SectionLevelStatus, string>> = {
  candidate: 'Кандидат',
  accepted: 'Принят',
  rejected: 'Отклонён',
};

export const levelStatusLabel = (status: SectionLevelStatus): string => STATUS_LABELS[status];

/** Подпись статуса уровня: автопринятие системой (ADR-0050) отличается от решения человека. */
export const levelDecisionLabel = (
  level: Pick<SectionLevelRead, 'status' | 'auto_accepted'>,
): string =>
  level.status === 'accepted' && level.auto_accepted ? 'Авто' : STATUS_LABELS[level.status];

export interface ISectionReview {
  /** Кандидаты: разногласия, нет разделения плиты, высота вне пределов - решает человек. */
  readonly review: readonly SectionLevelRead[];
  /** Принятые: системой (точное попадание в отметки) и человеком. */
  readonly accepted: readonly SectionLevelRead[];
  readonly rejected: readonly SectionLevelRead[];
  /** Сколько из принятых приняла система. */
  readonly auto: number;
}

/** Уровни листа по корзинам приёмки, внутри - сверху вниз по отметке. */
export const reviewBuckets = (levels: readonly SectionLevelRead[]): ISectionReview => {
  const ordered = [...levels].sort((a, b) => b.elevation_mm - a.elevation_mm || a.seq - b.seq);
  const accepted = ordered.filter((level) => level.status === 'accepted');
  return {
    review: ordered.filter((level) => level.status === 'candidate'),
    accepted,
    rejected: ordered.filter((level) => level.status === 'rejected'),
    auto: accepted.filter((level) => level.auto_accepted).length,
  };
};

/**
 * Область перехода к уровню на листе (доли листа): полоса уровня с запасом в этаж сверху и снизу,
 * чтобы были видны соседние отметки.
 */
export const levelFocusRect = (
  level: Pick<SectionLevelRead, 'markup'>,
): readonly [number, number, number, number] => {
  const [x0, y0, x1, y1] = level.markup.band;
  const height = Math.abs(y1 - y0);
  const width = Math.abs(x1 - x0);
  return [
    Math.max(0, Math.min(x0, x1) - width * 0.25),
    Math.max(0, Math.min(y0, y1) - height),
    Math.min(1, Math.max(x0, x1) + width * 0.25),
    Math.min(1, Math.max(y0, y1) + height),
  ];
};

/** Отметка в метрах с запятой и знаком: 47600 -> «+47,600», -3200 -> «-3,200», 0 -> «±0,000». */
export const formatMark = (mm: number): string => {
  const sign = mm > 0 ? '+' : mm < 0 ? '-' : '±';
  const abs = Math.abs(Math.round(mm));
  const meters = Math.floor(abs / 1000);
  const rest = String(abs % 1000).padStart(3, '0');
  return `${sign}${meters},${rest}`;
};

/** «в свету 3000 / пол+плита 300»; пусто - «высота не определена». */
export const formatLevelHeights = (
  level: Pick<SectionLevelRead, 'clear_height_mm' | 'structure_mm'>,
): string => {
  const parts: string[] = [];
  if (level.clear_height_mm !== null) parts.push(`в свету ${level.clear_height_mm}`);
  if (level.structure_mm !== null) parts.push(`пол+плита ${level.structure_mm}`);
  return parts.length > 0 ? parts.join(' / ') : 'высота не определена';
};

/** Этаж уровня: «Этаж 5» или «—». */
export const formatLevelFloor = (level: Pick<SectionLevelRead, 'floor'>): string =>
  level.floor === null ? '—' : `Этаж ${level.floor}`;

/** Высоту в свету сервер примет: задана и в пределах генератора трасс. */
export const hasValidClearHeight = (level: Pick<SectionLevelRead, 'clear_height_mm'>): boolean =>
  level.clear_height_mm !== null &&
  level.clear_height_mm >= CLEAR_HEIGHT_MIN_MM &&
  level.clear_height_mm <= CLEAR_HEIGHT_MAX_MM;

/** «Принять» доступно: уровень не принят и высота допустима. */
export const canAcceptLevel = (
  level: Pick<SectionLevelRead, 'status' | 'clear_height_mm'>,
): boolean => level.status !== 'accepted' && hasValidClearHeight(level);

/** Кандидаты с допустимой высотой: что принимает «Принять все на листе». */
export const acceptableCandidateIds = (levels: readonly SectionLevelRead[]): string[] =>
  levels
    .filter((level) => level.status === 'candidate' && hasValidClearHeight(level))
    .map((level) => level.id);

/** Уровни одной страницы, сверху вниз по отметке. */
export const levelsOfPage = (
  levels: readonly SectionLevelRead[],
  pageIndex: number,
): SectionLevelRead[] =>
  levels
    .filter((level) => level.page_index === pageIndex)
    .sort((a, b) => b.elevation_mm - a.elevation_mm || a.seq - b.seq);

export interface ISectionCutGroup {
  /** Обозначение линии разреза; `null` - не определено. */
  readonly cut: string | null;
  readonly label: string;
  readonly levels: readonly SectionLevelRead[];
}

/**
 * Уровни страницы по линии разреза: группы в порядке первого появления (по `seq`), внутри - сверху
 * вниз по отметке. Уровни без обозначения - одна группа в конце.
 */
export const groupLevelsByCut = (levels: readonly SectionLevelRead[]): ISectionCutGroup[] => {
  const ordered = [...levels].sort((a, b) => a.seq - b.seq);
  const byCut = new Map<string | null, SectionLevelRead[]>();
  for (const level of ordered) {
    const key = level.cut !== null && level.cut.trim() !== '' ? level.cut : null;
    byCut.set(key, [...(byCut.get(key) ?? []), level]);
  }
  const groups = [...byCut.entries()].map(([cut, items]) => ({
    cut,
    label: cut === null ? 'Разрез без обозначения' : `Разрез ${cut}`,
    levels: items.sort((a, b) => b.elevation_mm - a.elevation_mm || a.seq - b.seq),
  }));
  return [
    ...groups.filter((group) => group.cut !== null),
    ...groups.filter((group) => group.cut === null),
  ];
};

export interface ISectionCounts {
  readonly total: number;
  readonly accepted: number;
  readonly candidate: number;
  readonly rejected: number;
}

export const countLevels = (levels: readonly SectionLevelRead[]): ISectionCounts => {
  const count = (status: SectionLevelStatus) =>
    levels.filter((level) => level.status === status).length;
  return {
    total: levels.length,
    accepted: count('accepted'),
    candidate: count('candidate'),
    rejected: count('rejected'),
  };
};

export interface ISectionPageRow {
  readonly page: SectionPageRead;
  readonly counts: ISectionCounts;
}

/** Страницы-разрезы со сводкой по уровням, по номеру страницы. */
export const sectionPageRows = (
  pages: readonly SectionPageRead[],
  levels: readonly SectionLevelRead[],
): ISectionPageRow[] =>
  [...pages]
    .sort((a, b) => a.page_index - b.page_index)
    .map((page) => ({
      page,
      counts: countLevels(levels.filter((level) => level.page_index === page.page_index)),
    }));

/** Подпись страницы-разреза: заголовок, корпус, секция; без них - номер страницы. */
export const sectionPageLabel = (page: SectionPageRead): string => {
  const place = [
    page.corps !== null && page.corps !== '' ? `корп. ${page.corps}` : null,
    page.section !== null && page.section !== '' ? `сек. ${page.section}` : null,
  ].filter((part): part is string => part !== null);
  const title = page.title !== null && page.title.trim() !== '' ? page.title.trim() : null;
  const head = `Стр. ${page.page_index + 1}`;
  return [head, title, place.length > 0 ? place.join(', ') : null]
    .filter((part): part is string => part !== null)
    .join(' · ');
};

/** Замечания генератора по странице (без номера страницы - общие, на листе не показываются). */
export const issuesOfPage = (
  issues: readonly SectionIssueRead[],
  pageIndex: number,
): SectionIssueRead[] => issues.filter((issue) => issue.page_index === pageIndex);

/** Задание идёт: опрашивать результат. */
export const isSectionsJobActive = (status: string | undefined): boolean =>
  status === 'queued' || status === 'running';

/**
 * Текст отказа операции над разрезами. Отказ «принять нельзя» (422) несёт причину по конкретным
 * уровням - показывается она, а не общее «данные не приняты».
 */
export const sectionsErrorText = (error: unknown): string =>
  extractCode(error) === 'VALIDATION_FAILED'
    ? (extractMessage(error) ?? cadErrorText(error))
    : cadErrorText(error);
