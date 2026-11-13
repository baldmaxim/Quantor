'use client';

import type { CadProjectSummaryRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, Skeleton } from '@/components/ui';
import { useCadSummary } from '@/lib/cad/queue-queries';

/**
 * Сводка распознавания чертежей проекта: сколько листов готово, идёт, с ошибкой и не запускалось.
 * Данные - последние открываемые ревизии документов проекта (то же, что видит конвейер листов).
 */

export interface ICadRecognitionSummaryProps {
  readonly projectId: string;
}

interface ISegment {
  readonly key: 'done' | 'running' | 'failed' | 'idle';
  readonly label: string;
  /** Цвет полосы и точки подписи: только токены темы. */
  readonly color: string;
  readonly count: number;
}

const segmentsOf = (data: CadProjectSummaryRead): readonly ISegment[] => [
  { key: 'done', label: 'Готово', color: 'bg-success', count: data.sheets_done },
  { key: 'running', label: 'Идёт', color: 'bg-accent', count: data.sheets_running },
  { key: 'failed', label: 'Ошибки', color: 'bg-danger', count: data.sheets_failed },
  { key: 'idle', label: 'Не запускались', color: 'bg-border-strong', count: data.sheets_idle },
];

const WRAPPER = 'shrink-0 border-b border-border px-[var(--s-6)] py-[var(--s-4)]';

export const CadRecognitionSummary: FC<ICadRecognitionSummaryProps> = ({ projectId }) => {
  const summary = useCadSummary(projectId, true);
  const data = summary.data;

  if (summary.isPending) {
    return (
      <div className={WRAPPER}>
        <Skeleton className="h-[32px] w-auto" />
      </div>
    );
  }

  if (summary.isError || !data) {
    return (
      <div role="alert" className={`${WRAPPER} flex flex-wrap items-center gap-[var(--s-4)]`}>
        <span className="min-w-0 flex-1 text-xs text-danger">
          Не удалось получить сводку распознавания
        </span>
        <Button compact onClick={() => void summary.refetch()}>
          Повторить
        </Button>
      </div>
    );
  }

  if (data.sheets_total === 0) {
    return (
      <p data-testid="cad-recognition-summary" className={`${WRAPPER} m-0 text-xs text-muted`}>
        Листов для CAD нет
      </p>
    );
  }

  const segments = segmentsOf(data);
  const percent = Math.round((data.sheets_done / data.sheets_total) * 100);
  const shown = segments.filter((segment) => segment.count > 0);
  const description = `${segments
    .map((segment) => `${segment.label.toLowerCase()} ${segment.count}`)
    .join(', ')} из ${data.sheets_total} листов`;

  return (
    <div data-testid="cad-recognition-summary" className={WRAPPER}>
      <p className="m-0 text-xs font-medium text-text">
        Распознавание: {data.sheets_done} из {data.sheets_total} листов · {percent} %
      </p>
      <div
        role="img"
        aria-label={description}
        className="mt-[var(--s-3)] flex h-[6px] overflow-hidden rounded-full bg-surface-muted"
      >
        {segments
          .filter((segment) => segment.key !== 'idle' && segment.count > 0)
          .map((segment) => (
            <span
              key={segment.key}
              className={`h-full ${segment.color}`}
              style={{ width: `${(segment.count / data.sheets_total) * 100}%` }}
            />
          ))}
      </div>
      <ul className="m-0 mt-[var(--s-3)] flex list-none flex-wrap gap-x-[var(--s-5)] gap-y-[var(--s-2)] p-0 text-xs text-muted">
        {shown.map((segment) => (
          <li key={segment.key} className="flex items-center gap-[var(--s-3)]">
            <span aria-hidden="true" className={`size-[6px] rounded-full ${segment.color}`} />
            {segment.label} {segment.count}
          </li>
        ))}
      </ul>
    </div>
  );
};
