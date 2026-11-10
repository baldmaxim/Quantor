/**
 * Чистые вычисления для экрана CAD: время по часам сервера и подписи страниц.
 * Страницы в API нумеруются с 0 (`index`), пользователю показываются с 1.
 */

/** Номер страницы PDF для показа: индекс + 1. */
export const pageNumber = (index: number): number => index + 1;

/** «Стр. 3» — страница PDF по индексу. */
export const pageLabel = (index: number): string => `Стр. ${pageNumber(index)}`;

/** «Стр. 3 · вид 2» — вид на странице. */
export const viewLabel = (pageIndex: number, view: number): string =>
  `${pageLabel(pageIndex)} · вид ${view}`;

/** Какие страницы запрошены: `null` — все плановые, иначе перечень номеров. */
export const requestedPagesLabel = (requested: readonly number[] | null | undefined): string => {
  if (!requested || requested.length === 0) {
    return 'все плановые';
  }
  return `стр. ${[...requested]
    .sort((a, b) => a - b)
    .map(pageNumber)
    .join(', ')}`;
};

/**
 * Смещение часов сервера относительно часов браузера, мс.
 * `receivedAtMs` — момент получения ответа в браузере (`dataUpdatedAt`).
 */
export const serverOffsetMs = (
  serverTime: string | null | undefined,
  receivedAtMs: number,
): number => {
  const server = serverTime ? Date.parse(serverTime) : Number.NaN;
  return Number.isFinite(server) && receivedAtMs > 0 ? server - receivedAtMs : 0;
};

/**
 * Длительность попытки в секундах.
 *
 * Завершённая считается по меткам сервера. Идущая — по часам сервера: `nowMs` браузера плюс
 * смещение, чтобы сбитые часы пользователя не искажали таймер. Нет начала — нет значения.
 */
export const attemptElapsedSeconds = (
  startedAt: string | null | undefined,
  finishedAt: string | null | undefined,
  running: boolean,
  nowMs: number,
  offsetMs: number,
): number | null => {
  const start = startedAt ? Date.parse(startedAt) : Number.NaN;
  if (!Number.isFinite(start)) {
    return null;
  }
  const finish = finishedAt ? Date.parse(finishedAt) : Number.NaN;
  const end = Number.isFinite(finish) ? finish : running ? nowMs + offsetMs : Number.NaN;
  if (!Number.isFinite(end)) {
    return null;
  }
  return Math.max(0, (end - start) / 1000);
};

/** Наибольшее значение таймера, уже показанное для попытки. */
export interface IElapsedPeak {
  readonly key: string;
  readonly value: number;
}

/**
 * Монотонный таймер идущей попытки: пока попытка идёт, показ не бывает меньше уже показанного
 * для того же `key` (смещение часов сервера уточняется с каждым ответом, и сырое значение может
 * шагнуть назад). Завершённая попытка - точное значение, без «потолка». Чистая функция.
 */
export const holdElapsed = (
  peak: IElapsedPeak | null,
  key: string,
  raw: number | null,
  running: boolean,
): { readonly shown: number | null; readonly peak: IElapsedPeak | null } => {
  if (!running || raw === null) {
    return { shown: raw, peak: null };
  }
  const floor = peak !== null && peak.key === key ? peak.value : 0;
  const shown = Math.max(raw, floor);
  return { shown, peak: { key, value: shown } };
};

/** Секунды от начала попытки до события; нет данных — `null`. */
export const secondsSince = (startedAt: string | null | undefined, at: string): number | null => {
  const start = startedAt ? Date.parse(startedAt) : Number.NaN;
  const moment = Date.parse(at);
  if (!Number.isFinite(start) || !Number.isFinite(moment)) {
    return null;
  }
  return Math.max(0, (moment - start) / 1000);
};

/** Время суток по часам браузера для подписи созданного задания. */
export const formatTime = (iso: string | null | undefined): string => {
  const value = iso ? new Date(iso) : null;
  if (!value || Number.isNaN(value.getTime())) {
    return '—';
  }
  return new Intl.DateTimeFormat('ru', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(value);
};
