'use client';

import type { CalcResultTraceRead, CalcTraceNode } from '@quantor/api-client';

import { formatExact } from '@/lib/calc/runs';
import { unitTitle } from '@/lib/calc/format';

/**
 * «Почему такое значение?»: результат → шаг → версия правила, входы → факт → свидетельство.
 * Дерево строит сервер из структуры расчёта; экран только раскрывает его.
 */

const KIND_TITLES: Record<CalcTraceNode['kind'], string> = {
  RESULT: 'Результат',
  ROUNDING: 'Округление',
  STEP: 'Шаг',
  RULE: 'Правило',
  ASSUMPTION: 'Допущение',
  FACT: 'Факт',
  EVIDENCE: 'Свидетельство',
  PARAMETER: 'Параметр',
  CONVERSION: 'Перевод единиц',
  PRIMITIVE: 'Вычислительный примитив',
};

const TraceNode = ({ node }: { node: CalcTraceNode }) => (
  <li className="flex flex-col gap-[var(--s-2)]">
    <div className="flex flex-col gap-[var(--s-1)] rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-4)] py-[var(--s-3)]">
      <span className="text-micro tracking-[0.06em] text-muted uppercase">
        {KIND_TITLES[node.kind]} · <span className="font-mono normal-case">{node.key}</span>
      </span>
      <span className="font-medium wrap-anywhere">
        {node.title}
        {node.value != null && (
          <span className="tabular">
            {' '}
            = {formatExact(node.value)} {unitTitle(node.unit)}
          </span>
        )}
      </span>
      <span className="text-sm text-muted wrap-anywhere">{node.text}</span>
    </div>
    {node.children && node.children.length > 0 && (
      <ul className="ml-[var(--s-5)] flex list-none flex-col gap-[var(--s-2)] border-l border-border pl-[var(--s-4)]">
        {node.children.map((child) => (
          <TraceNode key={`${child.kind}:${child.key}`} node={child} />
        ))}
      </ul>
    )}
  </li>
);

export const RunTrace = ({ trace }: { trace: CalcResultTraceRead }) => (
  <div className="flex flex-col gap-[var(--s-4)]">
    <p className="max-w-[90ch] text-sm wrap-anywhere">{trace.text}</p>
    <ul className="flex list-none flex-col gap-[var(--s-2)]">
      <TraceNode node={trace.root} />
    </ul>
  </div>
);
