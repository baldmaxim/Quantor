/**
 * Словари CAD-пайплайна. Значения приходят с сервера; здесь только подписи и тон.
 * Неизвестное значение показывается как есть — ничего не выдумывается.
 */

export type CadBadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

/** Семь этапов штатного worker в порядке работы (ключи — `CadStageRead.key`). */
export const CAD_STAGES = [
  { key: 'source', label: 'Исходный PDF' },
  { key: 'regions', label: 'Область плана' },
  { key: 'scale', label: 'Масштаб' },
  { key: 'geometry', label: 'Элементы' },
  { key: 'assemblies', label: 'Узлы и помещения' },
  { key: 'checks', label: 'Контроль' },
  { key: 'export', label: 'Выпуск и отчёт' },
] as const;

export type CadStageKey = (typeof CAD_STAGES)[number]['key'];

const STATE_LABELS: Readonly<Record<string, string>> = {
  queued: 'В очереди',
  running: 'Выполняется',
  done: 'Выполнено',
  needs_review: 'Нужна проверка',
  error: 'Ошибка',
  failed: 'Отказ',
  unknown: 'Неизвестно',
};

const STATE_TONES: Readonly<Record<string, CadBadgeTone>> = {
  queued: 'neutral',
  running: 'accent',
  done: 'success',
  needs_review: 'warning',
  error: 'danger',
  failed: 'danger',
  unknown: 'neutral',
};

export const stateLabel = (status: string): string => STATE_LABELS[status] ?? status;
export const stateTone = (status: string): CadBadgeTone => STATE_TONES[status] ?? 'neutral';

/** Фазы попытки (runner и исполнитель Quantor), `CadEventRead.phase`. */
const PHASE_LABELS: Readonly<Record<string, string>> = {
  claimed: 'Задание захвачено исполнителем',
  download: 'Загрузка исходного PDF ревизии',
  starting: 'Запуск движка',
  verify: 'Проверка пакета движка',
  intake: 'Входной контроль PDF',
  worker: 'Обработка листов',
  collect: 'Сбор результатов',
  finished: 'Движок завершил работу',
  failed: 'Отказ',
  publish: 'Публикация файлов',
  published: 'Файлы опубликованы',
};

export const phaseLabel = (phase: string | null | undefined): string =>
  phase ? (PHASE_LABELS[phase] ?? phase) : '—';

/** Статус задания Quantor (`JobStatus`). */
const JOB_LABELS: Readonly<Record<string, string>> = {
  queued: 'В очереди',
  running: 'Выполняется',
  succeeded: 'Завершено',
  failed: 'Отказ',
  cancelled: 'Отменено',
};

const JOB_TONES: Readonly<Record<string, CadBadgeTone>> = {
  queued: 'neutral',
  running: 'accent',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'neutral',
};

export const jobLabel = (status: string): string => JOB_LABELS[status] ?? status;
export const jobTone = (status: string): CadBadgeTone => JOB_TONES[status] ?? 'neutral';

/** Исход попытки (`CadAttemptRead.outcome`). */
const OUTCOME_LABELS: Readonly<Record<string, string>> = {
  running: 'Выполняется',
  succeeded: 'Завершена',
  failed: 'Отказ',
  lost: 'Исполнитель потерян',
};

export const outcomeLabel = (outcome: string): string => OUTCOME_LABELS[outcome] ?? outcome;

/**
 * Итог результата. Ни один из них не является инженерной приёмкой: приёмка — отдельный шаг
 * человека, в QA-контуре не выполняется.
 */
const RESULT_LABELS: Readonly<Record<string, { label: string; tone: CadBadgeTone; hint: string }>> =
  {
    completed_requires_review: {
      label: 'DXF выпущен · нужна проверка инженером',
      tone: 'warning',
      hint: 'Кандидат движка. Масштаб подтверждён размерными цепочками; до приёмки инженером в работу не идёт.',
    },
    no_cad_review_required: {
      label: 'Только диагностика · DXF не создан',
      tone: 'warning',
      hint: 'Масштаб не подтверждён размерной проверкой: выпущена диагностика без DXF.',
    },
    failed: {
      label: 'Ошибка',
      tone: 'danger',
      hint: 'Попытка завершилась отказом; причина и этап — в деталях попытки.',
    },
  };

export const resultInfo = (
  status: string | null | undefined,
): { label: string; tone: CadBadgeTone; hint: string } | null =>
  status ? (RESULT_LABELS[status] ?? { label: status, tone: 'neutral', hint: '' }) : null;

/**
 * Длительность: до 10 с - с десятой долей, дальше секунды целые. Округление - один раз по
 * общему числу секунд, до деления на минуты (иначе 119,6 с давало «1 мин 60 с»).
 */
export const formatElapsed = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return '—';
  }
  const tenths = Math.round(seconds * 10) / 10;
  if (tenths < 10) {
    return `${tenths.toFixed(1)} с`;
  }
  const total = Math.round(seconds);
  if (total < 60) {
    return `${total} с`;
  }
  return `${Math.floor(total / 60)} мин ${total % 60} с`;
};
