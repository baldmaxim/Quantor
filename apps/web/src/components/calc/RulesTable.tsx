'use client';

import type { CalcRuleSummaryRead } from '@quantor/api-client';

import { StatusBadge, cx } from '@/components/ui';
import { RULE_STATUS, RULE_TYPE_TITLES } from '@/lib/calc/rules';

/**
 * Правила Quantor: по строке на правило. «Разрешено в расчёте» — ответ сервера: только
 * утверждённая действующая версия. Тендерное допущение подписано явно.
 *
 * На телефоне семь колонок не помещаются: строка разворачивается в карточку.
 */

const COLUMNS = 'minmax(220px,1.6fr) 90px 110px 150px 110px minmax(180px,1.2fr) 110px';

export const RulesTable = ({ items }: { items: readonly CalcRuleSummaryRead[] }) => (
  <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
    <div
      role="row"
      className="hidden items-center gap-[var(--s-5)] border-b border-border bg-surface-muted px-[var(--s-6)] py-[var(--s-4)] text-micro tracking-[0.06em] text-muted uppercase lg:grid"
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span>Правило</span>
      <span>Версия</span>
      <span>Система</span>
      <span>Тип</span>
      <span>Статус</span>
      <span>Источник</span>
      <span>В расчёте</span>
    </div>
    <ul className="list-none">
      {items.map((item) => (
        <RuleRow key={item.rule_key} item={item} />
      ))}
    </ul>
  </div>
);

const RuleRow = ({ item }: { item: CalcRuleSummaryRead }) => {
  const status = RULE_STATUS[item.latest_status];
  const version =
    item.approved_version !== null && item.approved_version !== item.latest_version
      ? `v${item.latest_version} · утв. v${item.approved_version}`
      : `v${item.latest_version}`;

  return (
    <li
      className={cx(
        'flex flex-wrap items-start gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] text-sm last:border-b-0',
        'lg:grid lg:gap-x-[var(--s-5)] lg:px-[var(--s-6)] lg:py-[var(--s-3)]',
      )}
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span className="flex min-w-0 basis-full flex-col lg:basis-auto">
        <span className="font-medium wrap-anywhere">{item.title}</span>
        <span className="font-mono text-xs text-muted wrap-anywhere">{item.rule_key}</span>
        {item.notice && <span className="text-xs text-warning">{item.notice}</span>}
      </span>
      <span className="tabular">{version}</span>
      <span className="text-muted">{item.systems.join(', ')}</span>
      <span className="text-xs">{RULE_TYPE_TITLES[item.rule_type]}</span>
      <span>
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
      </span>
      <span className="basis-full text-xs text-muted wrap-anywhere lg:basis-auto">
        {item.sources.length > 0 ? item.sources.join('; ') : 'источник не указан'}
      </span>
      <span>
        <StatusBadge tone={item.calculation_eligible ? 'success' : 'neutral'}>
          {item.calculation_eligible ? 'да' : 'нет'}
        </StatusBadge>
      </span>
    </li>
  );
};
