import type { CadQueueItemRead, JobType } from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';
import { countOf } from '@/lib/format';

import { cadCodeText } from './errors';
import { PIPELINE_STEP_LABELS, type PipelineStepKey } from './pipeline';

/** Показ очереди CAD без UI: метки заданий, статусы, место в очереди, страницы. */

const TASKS_FORMS = ['задание', 'задания', 'заданий'] as const;

/** Место задания в очереди исполнителя; число неизвестно (ещё не загружено) - `null`. */
export const queuePositionText = (ahead: number | null | undefined): string | null => {
  if (ahead === null || ahead === undefined) return null;
  return ahead === 0 ? 'Следующее на исполнение' : `Перед ним ${countOf(ahead, TASKS_FORMS)}`;
};

const STEP_OF_JOB: Readonly<Partial<Record<JobType, PipelineStepKey>>> = {
  cad_pdf_convert: 'convert',
  cad_walls: 'walls',
  cad_zones: 'zones',
  cad_mep_route: 'routes',
  cad_floor3d_dxf: 'floor3d',
};

/** Метка задания: те же слова, что у шагов конвейера листа; разрезы - своя вкладка. */
export const queueJobLabel = (jobType: JobType): string => {
  if (jobType === 'cad_sections') return 'Разрезы';
  const key = STEP_OF_JOB[jobType];
  return key === undefined ? jobType : PIPELINE_STEP_LABELS[key];
};

const CLOCK = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' });

export const clockText = (iso: string | null): string => {
  if (iso === null) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : CLOCK.format(date);
};

const withTime = (word: string, iso: string | null): string => {
  const time = clockText(iso);
  return time === '' ? word : `${word} ${time}`;
};

export interface IQueueStatusView {
  readonly tone: BadgeTone;
  readonly label: string;
}

/** Статус строки очереди: «Выполняется с ЧЧ:ММ», «В очереди · перед ним N» и т. д. */
export const queueStatusView = (item: CadQueueItemRead): IQueueStatusView => {
  switch (item.status) {
    case 'running':
      return { tone: 'accent', label: withTime('Выполняется с', item.started_at) };
    case 'queued': {
      const position = queuePositionText(item.ahead);
      return {
        tone: 'neutral',
        label: position === null ? 'В очереди' : `В очереди · ${position.toLowerCase()}`,
      };
    }
    case 'succeeded':
      return { tone: 'success', label: withTime('Готово', item.finished_at) };
    case 'failed':
      return { tone: 'danger', label: 'Ошибка' };
    case 'cancelled':
      return { tone: 'neutral', label: 'Отменено' };
  }
};

/** Текст ошибки задания по коду; кода нет или статус не «ошибка» - `null`. */
export const queueErrorText = (item: CadQueueItemRead): string | null =>
  item.status === 'failed' && item.error_code !== null ? cadCodeText(item.error_code) : null;

const PAGES_LISTED_MAX = 5;

/**
 * «стр. 3» или «стр. 3, 5»; страниц нет - `null`; много страниц - «12 стр.».
 * Индексы с 0 показываются с 1.
 */
export const queuePagesText = (pages: readonly number[]): string | null => {
  if (pages.length === 0) return null;
  if (pages.length > PAGES_LISTED_MAX) return `${pages.length} стр.`;
  return `стр. ${pages.map((page) => page + 1).join(', ')}`;
};
