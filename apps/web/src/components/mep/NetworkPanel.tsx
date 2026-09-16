'use client';

import type { MepScenarioRead } from '@quantor/api-client';
import type { FC } from 'react';

import { EmptyState, Field, InspectorSection, StatusBadge, cx } from '@/components/ui';
import {
  blockersFor,
  classLabel,
  decisionsFor,
  reviewOf,
  issuesFor,
  originOf,
  type IMepTrace,
  type MepSelection,
} from '@/lib/mep/trace';

import { InferenceStepCard } from './InferenceStepCard';
import {
  LegendSwatch,
  OriginBadge,
  Panel,
  TraceLinks,
  formatConfidence,
  formatValue,
} from './parts';

interface INetworkPanelProps {
  readonly scenario: MepScenarioRead;
  readonly trace: IMepTrace;
  readonly selectedId: string | null;
  readonly onSelect: (selection: MepSelection) => void;
}

/** Шаг 2: сгенерированная сеть уровня РД. Ни один элемент здесь не распознан на листе П. */
export const NetworkPanel: FC<INetworkPanelProps> = ({ scenario, trace, selectedId, onSelect }) => {
  const graph = scenario.network;
  const selected = selectedId ? trace.network.get(selectedId) : undefined;
  const items = [...trace.network.values()];
  // Проверку человеком берём из истории evidence, на который ссылается Derivation.
  const reviewedEvidence = (selected?.item.derivation.evidence_ids ?? []).filter((id) => {
    const element = trace.evidence.get(id);
    return element !== undefined && reviewOf(element) !== null;
  });

  return (
    <Panel
      title="Сеть уровня РД"
      aside={<StatusBadge tone="warning">сгенерировано, не распознано на П</StatusBadge>}
    >
      <p className="text-xs text-muted">
        Геометрия построена генератором поверх evidence П. Происхождение каждого элемента и
        параметра — ниже.
      </p>
      <div className="flex flex-wrap gap-[var(--s-5)]">
        <LegendSwatch style="observed">evidence П (подложка)</LegendSwatch>
        <LegendSwatch style="evidence">по evidence</LegendSwatch>
        <LegendSwatch style="rule">по правилу</LegendSwatch>
        <LegendSwatch style="prior">по опыту РД</LegendSwatch>
        <LegendSwatch style="unresolved">не определено</LegendSwatch>
      </div>

      <ul aria-label="Элементы сети" className="flex flex-col">
        {items.map(({ kind, item }) => (
          <li key={item.id}>
            <button
              type="button"
              aria-pressed={item.id === selectedId}
              onClick={() => onSelect({ kind: 'network', id: item.id })}
              className={cx(
                'flex min-h-[var(--h-row-tree)] w-full flex-wrap items-center gap-[var(--s-3)] px-[var(--s-3)] text-left text-sm',
                item.id === selectedId ? 'bg-accent-soft' : 'hover:bg-surface-muted',
              )}
            >
              <span className="mono text-xs">{item.id}</span>
              <span className="min-w-0 flex-1 truncate">
                {kind === 'node' ? item.role : 'участок'} · {classLabel(scenario, item.class_key)}
              </span>
              <OriginBadge origin={originOf(item.derivation)} />
            </button>
          </li>
        ))}
      </ul>

      {selected ? (
        <div className="flex flex-col gap-[var(--s-5)]">
          <InspectorSection
            title={`${selected.kind === 'node' ? 'Узел' : 'Участок'} ${selected.item.id}`}
          >
            <dl className="grid grid-cols-[auto_1fr] gap-x-[var(--s-5)] gap-y-[var(--s-2)]">
              <Field label="Класс профиля">
                {classLabel(scenario, selected.item.class_key)} ·{' '}
                {selected.item.class_key ?? 'null'}
              </Field>
              {selected.kind === 'node' ? (
                <Field label="Роль">{selected.item.role}</Field>
              ) : (
                <Field label="Порты">
                  {selected.item.start.node_id}/{selected.item.start.port_id} →{' '}
                  {selected.item.end.node_id}/{selected.item.end.port_id}
                </Field>
              )}
              <Field label="Происхождение">
                <OriginBadge origin={originOf(selected.item.derivation)} />
              </Field>
              <Field label="Derivation">{selected.item.derivation.provenance}</Field>
              <Field label="Уверенность">
                {formatConfidence(selected.item.derivation.confidence)}
              </Field>
              <Field label="Evidence">
                <TraceLinks
                  ids={selected.item.derivation.evidence_ids ?? []}
                  onClick={(id) => onSelect({ kind: 'evidence', id })}
                  empty="нет — на листе П не показан"
                />
              </Field>
              {reviewedEvidence.length > 0 && (
                <Field label="Проверка">
                  <StatusBadge tone="accent">evidence проверен человеком</StatusBadge>{' '}
                  {reviewedEvidence.join(', ')}
                </Field>
              )}
              <Field label="Строки ВОР">
                <TraceLinks
                  ids={trace.linesByNetwork.get(selected.item.id) ?? []}
                  onClick={(id) => onSelect({ kind: 'line', id })}
                  empty="не вошёл в ВОР"
                />
              </Field>
              <Field label="Участник строк">
                <TraceLinks
                  ids={trace.linesByParticipant.get(selected.item.id) ?? []}
                  onClick={(id) => onSelect({ kind: 'line', id })}
                />
              </Field>
            </dl>
          </InspectorSection>

          <InspectorSection title="Шаги вывода">
            <div className="flex flex-col gap-[var(--s-3)]">
              {(selected.item.derivation.step_ids ?? []).map((stepId) => (
                <InferenceStepCard
                  key={stepId}
                  network={graph}
                  stepId={stepId}
                  onSelect={onSelect}
                />
              ))}
              {(selected.item.derivation.step_ids ?? []).length === 0 && (
                <p className="text-xs text-muted">—</p>
              )}
            </div>
          </InspectorSection>

          {(selected.item.parameters ?? []).length > 0 && (
            <InspectorSection title="Параметры">
              <ul className="flex flex-col gap-[var(--s-3)] text-xs">
                {(selected.item.parameters ?? []).map((parameter) => (
                  <li key={parameter.key} className="flex flex-wrap items-center gap-[var(--s-3)]">
                    <span className="mono">{parameter.key}</span> ={' '}
                    {formatValue(parameter.value, parameter.unit)}
                    <OriginBadge origin={originOf(parameter.derivation)} />
                    <span className="text-muted">
                      шаги {(parameter.derivation.step_ids ?? []).join(', ') || '—'}
                    </span>
                    <TraceLinks
                      ids={parameter.derivation.evidence_ids ?? []}
                      onClick={(id) => onSelect({ kind: 'evidence', id })}
                      empty=""
                    />
                  </li>
                ))}
              </ul>
            </InspectorSection>
          )}

          {[...decisionsFor(scenario, selected.item.id)].map((decision) => (
            <p key={decision.id} className="text-xs text-danger">
              Нерешённый вопрос {decision.id}: {decision.code}
              {decision.blocks_quantity ? ' · блокирует ВОР' : ''}
              {decision.note ? ` — ${decision.note}` : ''}
            </p>
          ))}
          {[...blockersFor(scenario, selected.item.id)].map((blocker) => (
            <p key={`${blocker.code}:${blocker.key ?? ''}`} className="text-xs text-danger">
              Блокер ВОР {blocker.code}
              {blocker.key ? ` (${blocker.key})` : ''}: {blocker.message}
            </p>
          ))}
          {issuesFor(scenario.network_issues, selected.item.id).map((issue) => (
            <p key={issue.code} className="text-xs text-danger">
              {issue.code}: {issue.message}
            </p>
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          title="Выберите элемент сети"
          description="Покажем, из чего и каким шагом он построен."
        />
      )}
    </Panel>
  );
};
