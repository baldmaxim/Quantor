'use client';

import type { CalcSynthesisTraceNode, CalcSynthesisTraceRead } from '@quantor/api-client';

import { RunTrace } from '@/components/calc/RunTrace';

/**
 * «Почему Quantor считает, что этот элемент нужен?»: элемент → решение → правило, результат
 * расчёта (с цепочкой ядра до факта), факт → свидетельство, допущение. Дерево строит сервер.
 */

const KIND_TITLES: Record<CalcSynthesisTraceNode['kind'], string> = {
  ELEMENT: 'Элемент',
  DECISION: 'Выбор',
  RULE: 'Правило',
  CALCULATION_RESULT: 'Результат расчёта',
  FACT: 'Факт',
  EVIDENCE: 'Свидетельство',
  ASSUMPTION: 'Допущение',
  HUMAN_DECISION: 'Решение инженера',
};

const TraceItem = ({ node }: { node: CalcSynthesisTraceNode }) => (
  <li className="flex flex-col gap-[var(--s-2)]">
    <div className="flex flex-col gap-[var(--s-1)] rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-4)] py-[var(--s-3)]">
      <span className="text-micro tracking-[0.06em] text-muted uppercase">
        {KIND_TITLES[node.kind]} · <span className="font-mono normal-case">{node.key}</span>
      </span>
      <span className="font-medium wrap-anywhere">{node.title}</span>
      <span className="text-sm text-muted wrap-anywhere">{node.text}</span>
      {node.calculation && <RunTrace trace={node.calculation} />}
    </div>
    {node.children && node.children.length > 0 && (
      <ul className="ml-[var(--s-5)] flex list-none flex-col gap-[var(--s-2)] border-l border-border pl-[var(--s-4)]">
        {node.children.map((child) => (
          <TraceItem key={`${child.kind}:${child.key}`} node={child} />
        ))}
      </ul>
    )}
  </li>
);

export const SynthesisTrace = ({ trace }: { trace: CalcSynthesisTraceRead }) => (
  <ul className="flex list-none flex-col gap-[var(--s-2)]">
    <TraceItem node={trace.root} />
  </ul>
);
