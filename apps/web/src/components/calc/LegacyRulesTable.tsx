'use client';

import type { CalcLegacyRuleRead } from '@quantor/api-client';

import { StatusBadge, cx } from '@/components/ui';
import {
  LEGACY_ACTION_TITLES,
  LEGACY_CATALOG_TITLES,
  LEGACY_CLASS_TITLES,
  LEGACY_HAZARD_TITLES,
} from '@/lib/calc/rules';

/**
 * Карантин старого портала: только чтение. Каждая строка — «не проверено, в расчёте не
 * используется»: так отвечает сервер, и интерфейс это не переопределяет.
 */

const COLUMNS = '120px 110px minmax(220px,1.6fr) 150px minmax(160px,1fr) 150px 170px';

export const LegacyRulesTable = ({ items }: { items: readonly CalcLegacyRuleRead[] }) => (
  <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
    <div
      role="row"
      className="hidden items-center gap-[var(--s-5)] border-b border-border bg-surface-muted px-[var(--s-6)] py-[var(--s-4)] text-micro tracking-[0.06em] text-muted uppercase lg:grid"
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span>Legacy ID</span>
      <span>Система</span>
      <span>Правило</span>
      <span>Класс</span>
      <span>Опасности</span>
      <span>Предлагаемое действие</span>
      <span>Статус</span>
    </div>
    <ul className="list-none">
      {items.map((item) => (
        <LegacyRow key={item.legacy_id} item={item} />
      ))}
    </ul>
  </div>
);

const LegacyRow = ({ item }: { item: CalcLegacyRuleRead }) => (
  <li
    className={cx(
      'flex flex-wrap items-start gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] text-sm last:border-b-0',
      'lg:grid lg:gap-x-[var(--s-5)] lg:px-[var(--s-6)] lg:py-[var(--s-3)]',
    )}
    style={{ gridTemplateColumns: COLUMNS }}
  >
    <span className="font-mono text-xs">{item.legacy_id}</span>
    <span className="text-muted">{LEGACY_CATALOG_TITLES[item.catalog]}</span>
    <span className="basis-full wrap-anywhere lg:basis-auto">{item.rule_text}</span>
    <span className="text-xs">{LEGACY_CLASS_TITLES[item.class_primary]}</span>
    <span className="flex flex-wrap gap-[var(--s-2)]">
      {item.hazards.length === 0 ? (
        <span className="text-xs text-muted">не выявлены</span>
      ) : (
        item.hazards.map((hazard) => (
          <StatusBadge key={hazard} tone="danger" dot={false}>
            {LEGACY_HAZARD_TITLES[hazard]}
          </StatusBadge>
        ))
      )}
    </span>
    <span className="text-xs">
      {item.actions.map((action) => LEGACY_ACTION_TITLES[action]).join(', ')}
    </span>
    <span className="flex flex-col gap-[var(--s-1)]">
      <StatusBadge tone="warning">НЕ ПРОВЕРЕНО</StatusBadge>
      <span className="text-xs text-muted">
        {item.calculation_eligible ? 'в расчёте' : 'В РАСЧЁТЕ НЕ ИСПОЛЬЗУЕТСЯ'}
      </span>
    </span>
  </li>
);
