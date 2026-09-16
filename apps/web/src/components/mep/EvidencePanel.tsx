'use client';

import type { EvidenceElement, EvidenceInputMode, MepScenarioRead } from '@quantor/api-client';
import type { FC } from 'react';

import { EmptyState, Field, InspectorSection, StatusBadge, cx } from '@/components/ui';
import {
  classLabel,
  issuesFor,
  reviewOf,
  type IMepTrace,
  type MepSelection,
} from '@/lib/mep/trace';

import { ObservedBadge, Panel, TraceLinks, formatConfidence, formatValue } from './parts';

const REVIEW_LABEL = {
  corrected: 'исправлено человеком',
  confirmed: 'подтверждено человеком',
  added: 'добавлено человеком',
} as const;

const geometryText = (geometry: EvidenceElement['geometry']): string => {
  switch (geometry.kind) {
    case 'point':
      return `point ${geometry.point.join('; ')}`;
    case 'bbox':
      return `bbox ${geometry.min.join('; ')} – ${geometry.max.join('; ')}`;
    case 'polyline':
      return `polyline ${geometry.points.length} точ.`;
    case 'polygon':
      return `polygon ${geometry.outer.length} верш.`;
  }
};

const attributesText = (attributes: EvidenceElement['attributes']): string =>
  (attributes ?? []).map((item) => `${item.key}=${String(item.value)}`).join(', ') || '—';

interface IEvidencePanelProps {
  readonly scenario: MepScenarioRead;
  readonly trace: IMepTrace;
  readonly selectedId: string | null;
  readonly onSelect: (selection: MepSelection) => void;
}

const MODES: readonly { readonly mode: EvidenceInputMode; readonly hint: string }[] = [
  { mode: 'MODEL_EXTRACTED', hint: 'распознано моделью, без участия человека' },
  { mode: 'HUMAN_GT', hint: 'эталонная разметка человека' },
  { mode: 'HYBRID_REVIEWED', hint: 'предсказание модели, проверенное человеком' },
];

/** Шаг 1: что показано на листе П. Здесь нет ничего сгенерированного. */
export const EvidencePanel: FC<IEvidencePanelProps> = ({
  scenario,
  trace,
  selectedId,
  onSelect,
}) => {
  const graph = scenario.evidence;
  const selected = selectedId ? trace.evidence.get(selectedId) : undefined;

  return (
    <Panel title="Стадия П · evidence" aside={<ObservedBadge />}>
      <ul aria-label="Режим входа" className="flex flex-wrap gap-[var(--s-3)]">
        {MODES.map(({ mode, hint }) => (
          <li key={mode} title={hint}>
            <StatusBadge
              tone={graph.input_mode === mode ? 'accent' : 'neutral'}
              dot={graph.input_mode === mode}
            >
              <span className="mono">{mode}</span>
            </StatusBadge>
          </li>
        ))}
      </ul>
      {graph.input_mode === 'HYBRID_REVIEWED' && (
        <p className="text-xs text-warning">
          Evidence проверен человеком: исправленные элементы — разметка инженера, исходные
          предсказания модели сохранены рядом и в расчёт не идут.
        </p>
      )}

      <ul aria-label="Элементы evidence" className="flex flex-col">
        {graph.elements.map((element) => (
          <li key={element.id}>
            <button
              type="button"
              aria-pressed={element.id === selectedId}
              onClick={() => onSelect({ kind: 'evidence', id: element.id })}
              className={cx(
                'flex min-h-[var(--h-row-tree)] w-full items-center gap-[var(--s-3)] px-[var(--s-3)] text-left text-sm',
                element.id === selectedId ? 'bg-accent-soft text-accent' : 'hover:bg-surface-muted',
              )}
            >
              <span className="mono text-xs">{element.id}</span>
              <span className="min-w-0 flex-1 truncate">
                {classLabel(scenario, element.class_key)}
              </span>
              {reviewOf(element) ? (
                <StatusBadge tone={reviewOf(element) === 'confirmed' ? 'success' : 'warning'}>
                  {REVIEW_LABEL[reviewOf(element) ?? 'confirmed']}
                </StatusBadge>
              ) : null}
              <span className="tabular text-xs text-muted">
                {formatConfidence(element.confidence)}
              </span>
            </button>
          </li>
        ))}
      </ul>

      {selected ? (
        <div className="flex flex-col gap-[var(--s-5)]">
          <InspectorSection title={`Evidence ${selected.id}`}>
            <dl className="grid grid-cols-[auto_1fr] gap-x-[var(--s-5)] gap-y-[var(--s-2)]">
              <Field label="Класс профиля">
                {classLabel(scenario, selected.class_key)} · {selected.class_key ?? 'null'}
              </Field>
              <Field label="Вид">{selected.kind}</Field>
              <Field label="Геометрия на листе">
                {selected.geometry.kind} · {selected.sheet_id}
              </Field>
              {selected.text ? <Field label="Текст">{selected.text}</Field> : null}
              <Field label="Уверенность">{formatConfidence(selected.confidence)}</Field>
              <Field label="Происхождение">{selected.provenance}</Field>
              <Field label="Статус">{selected.status}</Field>
              <Field label="Проверка">{selected.review ?? 'unreviewed'}</Field>
            </dl>
          </InspectorSection>
          <InspectorSection title="Источники">
            <ul className="flex flex-col gap-[var(--s-2)] text-xs">
              {selected.sources.map((source) => (
                <li key={`${source.source_type}:${source.ref_id}`} className="mono">
                  {source.source_type} · {source.ref_id}
                  {source.tool_id ? ` · ${source.tool_id}` : ''}
                </li>
              ))}
            </ul>
          </InspectorSection>
          {(selected.attributes ?? []).length > 0 && (
            <InspectorSection title="Атрибуты">
              <ul className="flex flex-col gap-[var(--s-3)] text-xs">
                {(selected.attributes ?? []).map((attribute) => (
                  <li key={attribute.key} className="flex flex-wrap items-center gap-[var(--s-3)]">
                    <span className="mono">{attribute.key}</span> ={' '}
                    {formatValue(attribute.value, attribute.unit)}
                    <span className="text-muted">{attribute.status}</span>
                    <TraceLinks
                      ids={attribute.source_element_ids ?? []}
                      onClick={(id) => onSelect({ kind: 'evidence', id })}
                    />
                  </li>
                ))}
              </ul>
            </InspectorSection>
          )}
          {(selected.unresolved ?? []).length > 0 && (
            <InspectorSection title="Не определено">
              <ul className="flex flex-col gap-[var(--s-2)] text-xs text-danger">
                {(selected.unresolved ?? []).map((item) => (
                  <li key={item.field}>
                    {item.field}: {item.reason}
                  </li>
                ))}
              </ul>
            </InspectorSection>
          )}
          {(selected.original || (selected.review_history ?? []).length > 0) && (
            <InspectorSection title="Проверка человеком">
              {selected.original ? (
                <table aria-label="Модель и человек" className="mb-[var(--s-3)] w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted">
                      <th className="pr-[var(--s-4)] font-medium">Поле</th>
                      <th className="pr-[var(--s-4)] font-medium">
                        Предсказание модели ({selected.original.tool_id})
                      </th>
                      <th className="font-medium">После проверки</th>
                    </tr>
                  </thead>
                  <tbody className="mono">
                    <tr>
                      <td className="pr-[var(--s-4)]">класс</td>
                      <td className="pr-[var(--s-4)]">{selected.original.class_key ?? 'null'}</td>
                      <td>{selected.class_key ?? 'null'}</td>
                    </tr>
                    <tr>
                      <td className="pr-[var(--s-4)]">геометрия</td>
                      <td className="pr-[var(--s-4)]">
                        {geometryText(selected.original.geometry)}
                      </td>
                      <td>{geometryText(selected.geometry)}</td>
                    </tr>
                    <tr>
                      <td className="pr-[var(--s-4)]">атрибуты</td>
                      <td className="pr-[var(--s-4)]">
                        {attributesText(selected.original.attributes)}
                      </td>
                      <td>{attributesText(selected.attributes)}</td>
                    </tr>
                    <tr>
                      <td className="pr-[var(--s-4)]">уверенность</td>
                      <td className="pr-[var(--s-4)]">
                        {formatConfidence(selected.original.confidence)}
                      </td>
                      <td>{selected.provenance}</td>
                    </tr>
                  </tbody>
                </table>
              ) : null}
              <ol className="flex flex-col gap-[var(--s-2)] text-xs">
                {(selected.review_history ?? []).map((event) => (
                  <li key={event.event_id} className="mono">
                    {event.reviewed_at} · {event.reviewer_id} · {event.action}
                    {event.note ? ` — ${event.note}` : ''}
                  </li>
                ))}
              </ol>
            </InspectorSection>
          )}
          <InspectorSection title="Использовано генератором">
            <dl className="grid grid-cols-[auto_1fr] gap-x-[var(--s-5)] gap-y-[var(--s-3)]">
              <Field label="Элементы сети">
                <TraceLinks
                  ids={trace.networkByEvidence.get(selected.id) ?? []}
                  onClick={(id) => onSelect({ kind: 'network', id })}
                  empty="не используется"
                />
              </Field>
              <Field label="Шаги вывода">
                {(trace.stepsByEvidence.get(selected.id) ?? []).join(', ') || '—'}
              </Field>
            </dl>
          </InspectorSection>
          {issuesFor(scenario.evidence_issues, selected.id).map((issue) => (
            <p key={issue.code} className="text-xs text-danger">
              {issue.code}: {issue.message}
            </p>
          ))}
        </div>
      ) : (
        <EmptyState
          compact
          title="Выберите элемент"
          description="На листе или в списке — покажем, откуда он взят."
        />
      )}

      {(graph.gaps ?? []).length > 0 && (
        <InspectorSection title="Пробелы входа">
          <ul className="flex flex-col gap-[var(--s-3)] text-xs">
            {(graph.gaps ?? []).map((gap) => (
              <li key={gap.code} className="flex flex-col gap-[var(--s-2)]">
                <span className="mono">{gap.code}</span>
                {gap.note ? <span className="text-muted">{gap.note}</span> : null}
                <TraceLinks
                  ids={gap.subject_ids ?? []}
                  onClick={(id) => onSelect({ kind: 'evidence', id })}
                />
              </li>
            ))}
          </ul>
        </InspectorSection>
      )}
    </Panel>
  );
};
