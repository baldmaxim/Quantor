'use client';

import type { MepNetworkGraph } from '@quantor/api-client';
import type { FC } from 'react';

import { Field } from '@/components/ui';
import type { MepSelection } from '@/lib/mep/trace';

import { TraceLinks, formatConfidence } from './parts';

interface IInferenceStepCardProps {
  readonly network: MepNetworkGraph;
  readonly stepId: string;
  readonly onSelect: (selection: MepSelection) => void;
}

const short = (hash: string | null | undefined): string => (hash ? `${hash.slice(0, 12)}…` : '—');

/** Шаг вывода генератора: метод, прогон, корпус или правило, входы. Только поля контракта. */
export const InferenceStepCard: FC<IInferenceStepCardProps> = ({ network, stepId, onSelect }) => {
  const step = (network.inference_steps ?? []).find((item) => item.id === stepId);
  if (!step) {
    return <p className="text-xs text-danger">Шаг {stepId} не найден в графе</p>;
  }
  const tool = network.tools.find((item) => item.tool_id === step.tool_id);
  const corpus = (network.corpora ?? []).find((item) => item.corpus_id === step.corpus_id);

  return (
    <article
      aria-label={`Шаг ${step.id}`}
      className="rounded-[var(--radius-sm)] border border-border p-[var(--s-4)]"
    >
      <dl className="grid grid-cols-[auto_1fr] gap-x-[var(--s-5)] gap-y-[var(--s-2)]">
        <Field label="Шаг">
          {step.id} · {step.kind}
        </Field>
        <Field label="Инструмент">
          {tool ? `${tool.name} ${tool.version}` : step.tool_id}
          {tool?.model_id ? ` · модель ${tool.model_id}` : ''}
          {tool?.rule_source ? ` · ${tool.rule_source}` : ''}
        </Field>
        <Field label="Прогон">
          {step.run_id ?? '—'}
          {network.run
            ? ` · ${network.run.git_commit}${network.run.dirty ? ' (dirty)' : ''} · config ${short(network.run.config_sha256)}`
            : ''}
        </Field>
        <Field label="Уверенность">{formatConfidence(step.confidence)}</Field>
        <Field label="Альтернатив">{step.alternatives_considered ?? 0}</Field>
        <Field label="Входные evidence">
          <TraceLinks
            ids={step.evidence_ids ?? []}
            onClick={(id) => onSelect({ kind: 'evidence', id })}
          />
        </Field>
        <Field label="Связи evidence">{(step.relation_ids ?? []).join(', ') || '—'}</Field>
        <Field label="Предыдущие шаги">{(step.input_step_ids ?? []).join(', ') || '—'}</Field>
        <Field label="Случаи корпуса">
          {(step.retrieved_case_ids ?? []).join(', ') || '—'}
          {corpus
            ? ` · ${corpus.corpus_id} (${corpus.split}, dataset ${short(corpus.dataset_fingerprint)})`
            : ''}
        </Field>
        <Field label="Правила">{(step.rule_ids ?? []).join(', ') || '—'}</Field>
        {(step.rationale ?? []).length > 0 && (
          <Field label="Обоснование">{(step.rationale ?? []).join(', ')}</Field>
        )}
      </dl>
    </article>
  );
};
