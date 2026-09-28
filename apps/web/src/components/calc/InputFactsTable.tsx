'use client';

import type { CalcFactTypeRead, CalcInputFactRead } from '@quantor/api-client';

import { StatusBadge, cx } from '@/components/ui';
import {
  CONFIDENCE_TITLES,
  REVIEW_TITLES,
  USAGE,
  formatSubject,
  formatSystem,
  formatValue,
  statedNote,
  unitTitle,
} from '@/lib/calc/format';

/**
 * Утверждения реестра: значение, место, источник и — ответом сервера — идёт ли оно в расчёт.
 *
 * На телефоне девять колонок не помещаются: строка разворачивается в карточку с теми же
 * данными, как в списке проектов.
 */

const COLUMNS =
  'minmax(180px,1.4fr) 90px 70px minmax(140px,1fr) 90px minmax(160px,1.2fr) 110px 90px 150px';

interface IInputFactsTableProps {
  items: readonly CalcInputFactRead[];
  factTypes: ReadonlyMap<string, CalcFactTypeRead>;
}

export const InputFactsTable = ({ items, factTypes }: IInputFactsTableProps) => (
  <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
    <div
      role="row"
      className="hidden items-center gap-[var(--s-5)] border-b border-border bg-surface-muted px-[var(--s-6)] py-[var(--s-4)] text-micro tracking-[0.06em] text-muted uppercase lg:grid"
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span>Факт</span>
      <span>Значение</span>
      <span>Ед.</span>
      <span>Область</span>
      <span>Система</span>
      <span>Источник</span>
      <span>Статус</span>
      <span>Уверенность</span>
      <span>В расчёте</span>
    </div>
    <ul className="list-none">
      {items.map((item) => (
        <FactRow key={item.fact.id} item={item} type={factTypes.get(item.fact.fact_type)} />
      ))}
    </ul>
  </div>
);

const FactRow = ({
  item,
  type,
}: {
  item: CalcInputFactRead;
  type: CalcFactTypeRead | undefined;
}) => {
  const { fact } = item;
  const usage = USAGE[item.usage];
  const qualifier = type?.qualifier_options.find(
    (option) => option.value === fact.subject.qualifier,
  )?.title;
  const stated = statedNote(fact);

  return (
    <li
      className={cx(
        'flex flex-wrap items-start gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] text-sm last:border-b-0',
        'lg:grid lg:gap-x-[var(--s-5)] lg:px-[var(--s-6)] lg:py-[var(--s-3)]',
      )}
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span className="flex min-w-0 basis-full flex-col lg:basis-auto">
        <span className="font-medium wrap-anywhere">{item.fact_type_title}</span>
        {fact.note && <span className="text-xs text-muted wrap-anywhere">{fact.note}</span>}
      </span>
      <span className="tabular flex flex-col">
        {formatValue(fact.value, type)}
        {stated && <span className="text-xs text-muted">{stated}</span>}
      </span>
      <span className="text-muted">{type?.unit_title ?? unitTitle(type?.unit) ?? ''}</span>
      <span className="wrap-anywhere">{formatSubject(fact.subject, qualifier)}</span>
      <span className="text-muted">{formatSystem(fact.subject)}</span>
      <span className="basis-full text-xs text-muted wrap-anywhere lg:basis-auto">
        {item.source_title}
      </span>
      <span className="text-xs">{REVIEW_TITLES[fact.review_status]}</span>
      <span className="text-xs">{CONFIDENCE_TITLES[fact.confidence]}</span>
      <span>
        <StatusBadge tone={usage.tone} wrap>
          {usage.label}
        </StatusBadge>
      </span>
    </li>
  );
};
