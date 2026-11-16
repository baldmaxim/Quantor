/** Выбор и подписи версий модели здания (ADR-0053). */

import type { ModelVersionRead } from '@quantor/api-client';

export type StatusTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export const MODEL_STATUS: Readonly<Record<string, { label: string; tone: StatusTone }>> = {
  uploading: { label: 'Загрузка', tone: 'neutral' },
  candidate: { label: 'Кандидат', tone: 'warning' },
  approved: { label: 'Утверждена', tone: 'success' },
  superseded: { label: 'Заменена', tone: 'neutral' },
};

/** Версия для открытия: утверждённая, иначе новейшая из законченных выгрузок. */
export const pickVersion = (items: readonly ModelVersionRead[]): string | null => {
  const approved = items.find((item) => item.status === 'approved');
  if (approved) return approved.id;
  return items.find((item) => item.status !== 'uploading')?.id ?? null;
};

export interface IImportView {
  readonly label: string;
  readonly tone: StatusTone;
}

const IMPORT_VIEWS: Readonly<Record<string, IImportView>> = {
  queued: { label: 'в очереди', tone: 'neutral' },
  running: { label: 'строится', tone: 'accent' },
  succeeded: { label: 'построена', tone: 'success' },
  failed: { label: 'не построена', tone: 'danger' },
  cancelled: { label: 'отменена', tone: 'neutral' },
};

export const importView = (status: string): IImportView =>
  IMPORT_VIEWS[status] ?? { label: status, tone: 'neutral' };

const IMPORT_ERRORS: Readonly<Record<string, string>> = {
  MODEL_IFC_NOT_FOUND: 'В проекте нет загруженных IFC: загрузите их как обычные документы.',
  FEATURE_DISABLED: 'Модель здания выключена для этого пространства.',
  PERMISSION_DENIED: 'Недостаточно прав, чтобы строить модель.',
};

/** Понятный текст отказа постановки импорта по коду ошибки API. */
export const importErrorText = (code: string | null): string =>
  (code !== null ? IMPORT_ERRORS[code] : undefined) ?? 'Не удалось поставить построение модели.';

/** Задание в работе: кнопку блокируем, ход опрашиваем. */
export const importActive = (status: string | null): boolean =>
  status === 'queued' || status === 'running';
