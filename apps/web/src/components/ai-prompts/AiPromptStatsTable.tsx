'use client';

import type { AiPromptStatsRow } from '@quantor/api-client';
import type { FC } from 'react';

import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui';
import { useAiPromptStats, type AiPromptRole } from '@/lib/ai-prompts/ai-prompt-queries';

/** Статистика прогонов по версиям роли: стоимость, время, вердикты, находки, судьба замечаний. */

const HEAD = 'px-[var(--s-4)] py-[var(--s-3)] text-left text-xs font-medium text-muted';
const CELL = 'px-[var(--s-4)] py-[var(--s-3)] align-top text-sm';

const usd = (value: number | null): string => (value === null ? '—' : `$${value.toFixed(2)}`);
const seconds = (value: number | null): string =>
  value === null ? '—' : `${(value / 1000).toFixed(1)} с`;
const pairs = (counts: Readonly<Record<string, number>>): string => {
  const parts = Object.entries(counts).map(([name, count]) => `${name}: ${count}`);
  return parts.length === 0 ? '—' : parts.join(', ');
};

export interface IAiPromptStatsTableProps {
  readonly role: AiPromptRole;
}

export const AiPromptStatsTable: FC<IAiPromptStatsTableProps> = ({ role }) => {
  const stats = useAiPromptStats();
  const rows: readonly AiPromptStatsRow[] = (stats.data?.rows ?? []).filter(
    (row) => row.role === role,
  );

  return (
    <section aria-label="Статистика по версиям" className="flex flex-col gap-[var(--s-4)]">
      <h2 className="m-0 text-sm font-medium">Статистика по версиям</h2>
      {stats.isPending && <SkeletonRows rows={3} />}
      {stats.isError && (
        <ErrorState title="Не удалось получить статистику" onRetry={() => void stats.refetch()} />
      )}
      {stats.data && rows.length === 0 && <EmptyState compact title="Версий нет" />}
      {rows.length > 0 && (
        <div className="overflow-x-auto overscroll-contain rounded-[var(--radius-md)] border border-border-strong bg-surface">
          <table className="w-full min-w-[820px] border-collapse">
            <thead>
              <tr className="border-b border-border">
                <th className={HEAD}>Версия</th>
                <th className={HEAD}>Прогонов (успешно / ошибок)</th>
                <th className={HEAD}>Стоимость (средняя / сумма)</th>
                <th className={HEAD}>Время</th>
                <th className={HEAD}>Вердикты</th>
                <th className={HEAD}>Находки</th>
                <th className={HEAD}>Замечания (открыто / решено / удалено)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.prompt_id} className="border-b border-border last:border-b-0">
                  <td className={CELL}>v{row.version}</td>
                  <td className={CELL}>
                    {row.runs_total} ({row.runs_succeeded} / {row.runs_failed})
                  </td>
                  <td className={CELL}>
                    {usd(row.cost_avg_usd)} / {usd(row.cost_sum_usd)}
                  </td>
                  <td className={CELL}>{seconds(row.duration_avg_ms)}</td>
                  <td className={CELL}>{pairs(row.verdicts)}</td>
                  <td className={CELL}>
                    {row.findings_total} · {pairs(row.findings_by_type)}
                  </td>
                  <td className={CELL}>
                    {row.remarks_open} / {row.remarks_resolved} / {row.remarks_deleted}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
