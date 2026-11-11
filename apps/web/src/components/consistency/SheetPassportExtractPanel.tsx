'use client';

import type { SheetPassportExtractSummary } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, ProgressRow, StatusBadge, type BadgeTone } from '@/components/ui';
import {
  useExtractSummary,
  useStartPassportExtract,
} from '@/lib/consistency/sheet-passport-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Запуск разбора листов комплекта и состояние задания.
 *
 * Состояние и итог берутся из `extract-summary` проекта, поэтому после перезагрузки страницы ход виден.
 */

interface IPanelProps {
  readonly projectId: string;
}

const jobView = (
  summary: SheetPassportExtractSummary | null | undefined,
): { tone: BadgeTone; label: string } | null => {
  if (!summary) {
    return null;
  }
  switch (summary.status) {
    case 'queued':
      return { tone: 'neutral', label: 'в очереди' };
    case 'running':
      return { tone: 'accent', label: 'идёт разбор' };
    case 'succeeded':
      return { tone: 'success', label: 'готово' };
    case 'failed':
      return { tone: 'danger', label: 'ошибка' };
    default:
      return { tone: 'neutral', label: 'отменено' };
  }
};

const num = (value: number | null | undefined): string => (value == null ? '—' : String(value));

const ExtractResult: FC<{ readonly summary: SheetPassportExtractSummary }> = ({ summary }) => (
  <div className="flex flex-col gap-[var(--s-2)] text-sm" data-testid="extract-result">
    <p>
      Разобрано файлов {num(summary.files_parsed)} из {num(summary.files_total)}, страниц{' '}
      {num(summary.pages)}; новых {num(summary.created)}, обновлено {num(summary.updated)}, не
      тронуто проверенных {num(summary.skipped_reviewed)}
    </p>
    {(summary.error_count ?? 0) > 0 && (
      <details>
        <summary className="cursor-pointer text-danger">
          Файлов с ошибкой: {num(summary.error_count)}
        </summary>
        <ul className="mt-[var(--s-2)] flex flex-col gap-[var(--s-1)] text-xs text-muted">
          {summary.errors.map((item) => (
            <li key={item.file_name} className="[overflow-wrap:anywhere]">
              {item.file_name} — {item.error}
            </li>
          ))}
        </ul>
      </details>
    )}
  </div>
);

export const SheetPassportExtractPanel: FC<IPanelProps> = ({ projectId }) => {
  const summaryQuery = useExtractSummary(projectId, true);
  const start = useStartPassportExtract(projectId);
  const current = summaryQuery.data;
  const view = jobView(current);
  const active = current?.status === 'queued' || current?.status === 'running';

  return (
    <section
      aria-label="Разбор листов"
      className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-5)] py-[var(--s-4)]"
    >
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <Button
          variant="primary"
          loading={start.isPending}
          disabled={active}
          onClick={() => start.mutate()}
        >
          Разобрать листы
        </Button>
        {view && <StatusBadge tone={view.tone}>{view.label}</StatusBadge>}
        <p className="min-w-0 flex-1 text-xs text-muted">
          Текстовый слой всех PDF проекта: раздел, тип листа, этажи и шифр по каждой странице.
          Результат — кандидаты, в работу идут подтверждённые человеком.
        </p>
      </div>
      {active && <ProgressRow value={current?.progress ?? null} label="Разбор листов" />}
      {current?.status === 'failed' && (
        <p role="alert" className="text-sm text-danger">
          {errorMessage(current.error_code ?? '')}
        </p>
      )}
      {current?.status === 'succeeded' && <ExtractResult summary={current} />}
      {start.isError && (
        <p role="alert" className="text-sm text-danger">
          {extractMessage(start.error) ?? errorMessage(extractCode(start.error))}
        </p>
      )}
    </section>
  );
};
