import type { ProjectJobSummary } from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';

/**
 * Приведение данных API к тому, что видит пользователь.
 *
 * Здесь и только здесь принимается решение, как назвать состояние по-русски. Тексты
 * не разбросаны по компонентам, поэтому переименование состояния — правка одного места.
 */

const SIZE_UNITS = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'] as const;

export const formatBytes = (bytes: number): string => {
  if (bytes <= 0) return '0 Б';

  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), SIZE_UNITS.length - 1);
  const value = bytes / 1024 ** index;
  // Байты дробной части не требуют; у остальных единиц она нужна только если значима:
  // «47 МБ» читается легче, чем «47,0 МБ».
  const digits = index === 0 || value >= 100 ? 0 : 1;
  const text = value.toFixed(digits).replace(/\.0$/, '').replace('.', ',');

  return `${text} ${SIZE_UNITS[index]}`;
};

const RELATIVE = new Intl.RelativeTimeFormat('ru', { numeric: 'auto' });
const TIME = new Intl.DateTimeFormat('ru', { hour: '2-digit', minute: '2-digit' });
const DATE = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'long' });
const DATE_WITH_YEAR = new Intl.DateTimeFormat('ru', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

/**
 * Время изменения в понятном виде.
 *
 * Сегодняшнее показывается часами, вчерашнее — словом, остальное — датой. Так строка
 * читается без вычислений в уме, а год не мозолит глаза у свежих проектов.
 */
export const formatWhen = (iso: string, now: Date = new Date()): string => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';

  const startOfDay = (value: Date) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const days = Math.round((startOfDay(date) - startOfDay(now)) / 86_400_000);

  if (days === 0) return `сегодня, ${TIME.format(date)}`;
  if (days === -1) return `вчера, ${TIME.format(date)}`;
  if (days > -7) return `${RELATIVE.format(days, 'day')}, ${TIME.format(date)}`;

  return date.getFullYear() === now.getFullYear() ? DATE.format(date) : DATE_WITH_YEAR.format(date);
};

export interface StatusView {
  readonly label: string;
  readonly tone: BadgeTone;
}

/**
 * Состояние проекта по его последнему заданию.
 *
 * Проект сам по себе не бывает «в процессе импорта» — это состояние задания.
 * Показываем именно его, а не выдуманный статус проекта.
 */
export const projectStatus = (job: ProjectJobSummary | null | undefined): StatusView | null => {
  if (!job) return null;

  switch (job.status) {
    case 'queued':
      return { label: 'В очереди', tone: 'warning' };
    case 'running': {
      const percent = job.progress === null ? null : Math.round(job.progress * 100);
      return {
        label: percent === null ? 'Импорт' : `Импорт ${percent} %`,
        tone: 'accent',
      };
    }
    case 'succeeded':
      return { label: 'Готов', tone: 'success' };
    case 'failed':
      return { label: 'Ошибка импорта', tone: 'danger' };
    case 'cancelled':
      return { label: 'Импорт отменён', tone: 'neutral' };
    default:
      return null;
  }
};

const PROCESSING_STATUS: Record<string, StatusView> = {
  pending: { label: 'В очереди', tone: 'warning' },
  importing: { label: 'Импортируется', tone: 'accent' },
  ready: { label: 'Готов', tone: 'success' },
  unprocessed: { label: 'Не распознан', tone: 'warning' },
  processor_unavailable: { label: 'Обработчик не подключён', tone: 'neutral' },
  failed: { label: 'Ошибка', tone: 'danger' },
};

export const revisionStatus = (status: string): StatusView =>
  PROCESSING_STATUS[status] ?? { label: status, tone: 'neutral' };

const DOCUMENT_KIND: Record<string, string> = {
  pdf: 'PDF',
  recognized_package: 'Распознанный пакет',
  revit: 'Revit',
  navisworks: 'Navisworks',
  ifc: 'IFC',
  other: 'Файл',
};

export const documentKind = (kind: string): string => DOCUMENT_KIND[kind] ?? kind;

const BLOCK_TYPE: Record<string, string> = {
  text: 'Текст',
  image: 'Изображение',
  stamp: 'Штамп',
};

export const blockType = (type: string): string => BLOCK_TYPE[type] ?? type;

/** Склонение существительных после числительного. */
export const plural = (count: number, forms: readonly [string, string, string]): string => {
  const abs = Math.abs(count) % 100;
  const tail = abs % 10;

  if (abs > 10 && abs < 20) return forms[2];
  if (tail > 1 && tail < 5) return forms[1];
  if (tail === 1) return forms[0];
  return forms[2];
};

export const countOf = (count: number, forms: readonly [string, string, string]): string =>
  `${count} ${plural(count, forms)}`;

export const DOCUMENTS_FORMS = ['документ', 'документа', 'документов'] as const;
export const SHEETS_FORMS = ['лист', 'листа', 'листов'] as const;
export const PROJECTS_FORMS = ['проект', 'проекта', 'проектов'] as const;
export const REGIONS_FORMS = ['область', 'области', 'областей'] as const;
