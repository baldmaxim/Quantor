import type { BadgeTone } from '@quantor/ui';

/**
 * Перевод состояний в подпись и тон — в одном месте.
 *
 * Главное правило этого файла: неизвестное состояние выглядит неизвестным.
 * `unknown` и `not_configured` не превращаются ни в «в порядке», ни в ноль —
 * панель, показывающая ноль вместо «не знаю», хуже пустой: по ней принимают решения.
 */

export type ProbeStatus = 'healthy' | 'degraded' | 'unavailable' | 'not_configured' | 'unknown';

interface IStatusView {
  readonly label: string;
  readonly tone: BadgeTone;
}

const VIEWS: Record<ProbeStatus, IStatusView> = {
  healthy: { label: 'в порядке', tone: 'success' },
  degraded: { label: 'с оговорками', tone: 'warning' },
  unavailable: { label: 'недоступно', tone: 'danger' },
  not_configured: { label: 'не настроено', tone: 'neutral' },
  unknown: { label: 'неизвестно', tone: 'neutral' },
};

export const statusView = (status: ProbeStatus): IStatusView => VIEWS[status];

/** Значение, которого нет. Прочерк, а не ноль и не пустая строка. */
export const NOT_MEASURED = '—';

export const formatCount = (value: number | null | undefined): string =>
  typeof value === 'number' ? String(value) : NOT_MEASURED;

/** Источники значений настроек и флагов на человеческом языке. */
const SOURCES: Record<string, string> = {
  default: 'умолчание кода',
  system: 'вся установка',
  workspace: 'рабочее пространство',
  deployment: 'окружение',
};

export const sourceLabel = (source: string): string => SOURCES[source] ?? source;

export const sourceTone = (source: string): BadgeTone =>
  source === 'default' ? 'neutral' : source === 'deployment' ? 'warning' : 'accent';
