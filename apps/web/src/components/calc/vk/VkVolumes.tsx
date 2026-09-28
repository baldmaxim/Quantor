'use client';

import type { CalcExpectedQuantityRead, CalcQuantityCategory } from '@quantor/api-client';
import { useState } from 'react';

import { TraceTree } from '@/components/calc/SynthesisTrace';
import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge, cx } from '@/components/ui';
import {
  CATEGORY_TITLES,
  COMPLETENESS,
  DERIVATION_TITLES,
  amountText,
  unitTitle,
} from '@/lib/calc/vk';
import { useVkTrace } from '@/lib/calc/vk-queries';

/**
 * Ожидаемые количества сценария. Каждая позиция раскрывается: составляющие («198 м —
 * вертикали», «магистраль — не определено»), тендерный резерв отдельно от базы, цепочка до
 * свидетельства. Неизвестное — «не определено», а не ноль; итог по трубам без неизвестного не
 * выдаётся за полный.
 */

const ORDER: CalcQuantityCategory[] = [
  'PIPE',
  'FITTING',
  'VALVE',
  'SLEEVE',
  'INSULATION',
  'SUPPORT',
  'EQUIPMENT',
  'CONNECTION',
  'OTHER',
];

const Breakdown = ({ row }: { row: CalcExpectedQuantityRead }) => (
  <div className="flex flex-col gap-[var(--s-2)] text-sm">
    {row.components.length > 0 && (
      <ul className="flex list-none flex-col gap-[var(--s-1)]">
        {row.components.map((item) => (
          <li key={item.key} className="flex flex-wrap gap-x-[var(--s-3)] wrap-anywhere">
            <span className="font-mono">{amountText(item.amount, item.unit)}</span>
            <span>— {item.title}</span>
            {item.note && <span className="text-muted">({item.note})</span>}
          </li>
        ))}
      </ul>
    )}
    {row.base && row.reserve && (
      <p className="wrap-anywhere">
        База: <span className="font-mono">{amountText(row.base, row.unit)}</span>; тендерный резерв:{' '}
        <span className="font-mono">+{amountText(row.reserve.amount, row.reserve.unit)}</span> (
        {row.reserve.rule_key}@{row.reserve.version}); итог:{' '}
        <span className="font-mono">{amountText(row.amount, row.unit)}</span>
      </p>
    )}
    {row.blocked_by.length > 0 && (
      <p className="text-muted wrap-anywhere">Не определено из-за: {row.blocked_by.join(', ')}</p>
    )}
    <p className="text-muted wrap-anywhere">{row.explanation}</p>
  </div>
);

const Trace = ({ quantityId }: { quantityId: string }) => {
  const trace = useVkTrace(quantityId);
  if (trace.isError)
    return <ErrorState title="Объяснение не загрузилось" onRetry={() => void trace.refetch()} />;
  if (!trace.data) return <SkeletonRows rows={3} />;
  return <TraceTree root={trace.data.root} />;
};

const Row = ({ row }: { row: CalcExpectedQuantityRead }) => {
  const [open, setOpen] = useState(false);
  const [traced, setTraced] = useState(false);
  const state = COMPLETENESS[row.completeness];
  return (
    <li
      className={cx(
        'flex flex-col gap-[var(--s-2)] px-[var(--s-4)] py-[var(--s-3)]',
        open && 'bg-accent-soft',
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex min-h-[44px] w-full flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-1)] text-left"
      >
        <span className="min-w-0 flex-1 font-medium wrap-anywhere">{row.title}</span>
        <span className="font-mono text-sm">
          {row.completeness === 'PARTIAL' && 'подтверждено '}
          {amountText(row.amount, row.unit)}
        </span>
        <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
        <span className="text-xs text-muted">{DERIVATION_TITLES[row.derivation]}</span>
        <span className="text-xs text-muted">
          {row.size ?? (row.category === 'PIPE' ? 'диаметр не определён' : '')}
        </span>
      </button>
      {row.notice && <p className="text-xs text-warning wrap-anywhere">{row.notice}</p>}
      {open && (
        <div className="flex flex-col gap-[var(--s-3)]">
          <Breakdown row={row} />
          {traced ? (
            <Trace quantityId={row.id} />
          ) : (
            <div>
              <Button compact onClick={() => setTraced(true)}>
                Почему это количество такое
              </Button>
            </div>
          )}
        </div>
      )}
    </li>
  );
};

export const VkVolumes = ({
  rows,
  isError,
  onRetry,
}: {
  rows: CalcExpectedQuantityRead[] | undefined;
  isError: boolean;
  onRetry: () => void;
}) => {
  if (isError) return <ErrorState title="Объёмы не загрузились" onRetry={onRetry} />;
  if (!rows) return <SkeletonRows rows={6} />;
  if (rows.length === 0) {
    return (
      <EmptyState
        compact
        title="Позиций нет"
        description="Расчёт системы заблокирован — см. «Неопределённости»."
      />
    );
  }
  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      {ORDER.filter((category) => rows.some((row) => row.category === category)).map((category) => (
        <section key={category} className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">{CATEGORY_TITLES[category]}</h3>
          <ul className="flex list-none flex-col divide-y divide-border overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
            {rows
              .filter((row) => row.category === category)
              .map((row) => (
                <Row key={row.id} row={row} />
              ))}
          </ul>
        </section>
      ))}
      <p className="text-xs text-muted">
        Единицы: {Array.from(new Set(rows.map((row) => unitTitle(row.unit)))).join(', ')}. Итог по
        трубам не суммируется с составляющими — это та же длина другим срезом.
      </p>
    </div>
  );
};
