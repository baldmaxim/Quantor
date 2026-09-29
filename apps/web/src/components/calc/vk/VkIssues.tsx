'use client';

import type { CalcAssumptionRecord, CalcPassportRead } from '@quantor/api-client';

import { EmptyState, ErrorState, SkeletonRows, StatusBadge } from '@/components/ui';
import { SCENARIO_TITLES } from '@/lib/calc/runs';

/**
 * Допущения и неопределённости паспорта. Допущение видно отдельно — применённое или нет и
 * почему; неопределённость названа вместе с тем, на что влияет и на что нет. Это не список
 * вопросов Заказчику (PROMPT 10): только структурированное «что Quantor не знает».
 */

export const VkAssumptions = ({
  passport,
  records,
  isError,
  onRetry,
}: {
  passport: CalcPassportRead;
  records: CalcAssumptionRecord[] | undefined;
  isError: boolean;
  onRetry: () => void;
}) => {
  if (isError) return <ErrorState title="Допущения не загрузились" onRetry={onRetry} />;
  if (!records) return <SkeletonRows rows={3} />;
  const scenarios = new Map(passport.runs.map((run) => [run.calculation_run_id, run.scenario]));
  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <ul className="flex list-disc flex-col gap-[var(--s-1)] pl-[var(--s-5)] text-sm">
        {passport.body.assumptions.map((line) => (
          <li key={line} className="wrap-anywhere">
            {line}
          </li>
        ))}
      </ul>
      {records.length > 0 && (
        <ul className="flex list-none flex-col divide-y divide-border rounded-[var(--radius-sm)] border border-border text-sm">
          {records.map((record, index) => (
            <li
              key={`${record.step_key}-${index}`}
              className="flex flex-col gap-[var(--s-1)] px-[var(--s-4)] py-[var(--s-2)]"
            >
              <span className="flex flex-wrap items-center gap-[var(--s-3)]">
                <StatusBadge tone={record.applied ? 'warning' : 'neutral'}>
                  {record.applied ? 'применено' : 'не применено'}
                </StatusBadge>
                <span className="font-mono text-xs">{record.rule_key ?? record.step_key}</span>
                <span className="text-xs text-muted">
                  разница {record.delta.replace('.', ',')} {record.unit ?? ''}
                </span>
              </span>
              <span className="text-xs text-muted wrap-anywhere">{record.reason}</span>
            </li>
          ))}
        </ul>
      )}
      {scenarios.size === 0 && <p className="text-sm text-muted">Расчёт не выполнялся.</p>}
      <p className="text-xs text-muted">
        Сценарии: {Object.values(SCENARIO_TITLES).join(' · ')}. Глобального процента запаса нет —
        только утверждённое тендерное допущение по своему классу позиций.
      </p>
    </div>
  );
};

type IssuesBody = Pick<CalcPassportRead['body'], 'unresolved' | 'conflicts' | 'warnings'>;

export const VkUnresolved = ({ body }: { body: IssuesBody }) => {
  const { unresolved: issues, conflicts, warnings } = body;
  if (issues.length === 0 && conflicts.length === 0 && warnings.length === 0) {
    return <EmptyState compact title="Неопределённостей нет" />;
  }
  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      {conflicts.length > 0 && (
        <section className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">Расхождения источников</h3>
          <ul className="flex list-none flex-col gap-[var(--s-1)] text-sm">
            {conflicts.map((item) => (
              <li key={`${item.fact_key}|${item.message}`} className="wrap-anywhere">
                {item.message} <span className="font-mono text-xs text-muted">{item.fact_key}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {warnings.length > 0 && (
        <section className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">Предупреждения расчёта</h3>
          <ul className="flex list-disc flex-col gap-[var(--s-1)] pl-[var(--s-5)] text-sm">
            {warnings.map((line) => (
              <li key={line} className="wrap-anywhere">
                {line}
              </li>
            ))}
          </ul>
        </section>
      )}
      {issues.length > 0 && <UnresolvedList issues={issues} />}
    </div>
  );
};

const UnresolvedList = ({ issues }: { issues: CalcPassportRead['body']['unresolved'] }) => (
  <ul className="flex list-none flex-col gap-[var(--s-2)]">
    {issues.map((issue) => (
      <li
        key={issue.key}
        className="flex flex-col gap-[var(--s-1)] rounded-[var(--radius-sm)] border border-border px-[var(--s-4)] py-[var(--s-3)] text-sm"
      >
        <span className="flex flex-wrap items-center gap-[var(--s-3)]">
          <span className="min-w-0 flex-1 font-medium wrap-anywhere">{issue.title}</span>
          {issue.structural && <StatusBadge tone="warning">структура</StatusBadge>}
          <span className="font-mono text-xs text-muted">{issue.key}</span>
        </span>
        <span className="wrap-anywhere">Известно: {issue.known}</span>
        <span className="wrap-anywhere">Нужно: {issue.needed}</span>
        {issue.blocks.length > 0 && (
          <span className="wrap-anywhere">Влияет на: {issue.blocks.join(', ')}</span>
        )}
        {issue.not_blocks.length > 0 && (
          <span className="text-muted wrap-anywhere">
            Не влияет на: {issue.not_blocks.join(', ')}
          </span>
        )}
      </li>
    ))}
  </ul>
);
