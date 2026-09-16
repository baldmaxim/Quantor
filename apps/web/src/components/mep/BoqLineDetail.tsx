'use client';

import type { BoqLine, SubjectRef } from '@quantor/api-client';
import type { FC } from 'react';

import { InspectorSection, StatusBadge } from '@/components/ui';
import { selectionFor, type MepSelection } from '@/lib/mep/trace';

import { TraceLink, formatValue } from './parts';

interface IBoqLineDetailProps {
  readonly line: BoqLine;
  readonly onSelect: (selection: MepSelection) => void;
}

const UNIT: Readonly<Record<string, string>> = { m: 'м', pcs: 'шт', mm: 'мм' };

const ROLE: Readonly<Record<string, string>> = {
  anchor: 'узел',
  connected: 'подключён',
  compared: 'сравнивается',
};

/** Ссылка на объект по виду: переход есть только туда, где на странице есть панель. */
export const SubjectLink: FC<{
  readonly subject: SubjectRef;
  readonly onSelect: (selection: MepSelection) => void;
  readonly suffix?: string;
}> = ({ subject, onSelect, suffix }) => {
  const target = selectionFor(subject);
  const label = `${subject.id}${suffix ?? ''}`;
  return (
    <span className="inline-flex items-center gap-[var(--s-2)]">
      <span className="text-micro text-muted">{subject.kind}</span>
      {target ? (
        <TraceLink id={label} onClick={() => onSelect(target)} />
      ) : (
        <span className="mono text-xs">{label}</span>
      )}
    </span>
  );
};

/**
 * Разбор строки ВОР по источникам. Все числа и ссылки — поля `BoqLine.sources`, выданные движком:
 * интерфейс не делит итог и не ищет, откуда взялось значение группы.
 */
export const BoqLineDetail: FC<IBoqLineDetailProps> = ({ line, onSelect }) => (
  <section aria-label="Разбор строки ВОР" className="flex flex-col gap-[var(--s-4)]">
    <InspectorSection
      title={`Строка ${line.line_id}`}
      aside={line.additive ? <StatusBadge tone="neutral">сумма вкладов</StatusBadge> : null}
    >
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="text-left text-muted">
            <th className="py-[var(--s-2)] pr-[var(--s-4)] font-medium">Источник</th>
            <th className="py-[var(--s-2)] pr-[var(--s-4)] text-right font-medium">Вклад</th>
            <th className="py-[var(--s-2)] pr-[var(--s-4)] font-medium">Значения группы ←</th>
            <th className="py-[var(--s-2)] font-medium">Участники</th>
          </tr>
        </thead>
        <tbody>
          {(line.sources ?? []).map((source) => (
            <tr key={source.subject.id} className="border-t border-border align-top">
              <td className="py-[var(--s-2)] pr-[var(--s-4)]">
                <SubjectLink subject={source.subject} onSelect={onSelect} />
              </td>
              <td className="tabular py-[var(--s-2)] pr-[var(--s-4)] text-right">
                {source.quantity === null || source.quantity === undefined
                  ? '—'
                  : `${source.quantity} ${UNIT[line.unit] ?? line.unit}`}
              </td>
              <td className="py-[var(--s-2)] pr-[var(--s-4)]">
                <ul className="flex flex-col gap-[var(--s-2)]">
                  {(source.group_values ?? []).map((ref) => (
                    <li key={ref.key} className="flex flex-wrap items-center gap-[var(--s-2)]">
                      <span className="mono">{ref.key}</span>
                      <span>←</span>
                      <SubjectLink
                        subject={ref.subject}
                        onSelect={onSelect}
                        suffix={`.parameters.${ref.parameter_key}`}
                      />
                    </li>
                  ))}
                </ul>
              </td>
              <td className="py-[var(--s-2)]">
                <ul className="flex flex-col gap-[var(--s-2)]">
                  {(source.participants ?? []).map((participant) => (
                    <li
                      key={`${participant.role}:${participant.subject.id}`}
                      className="flex flex-wrap items-center gap-[var(--s-2)]"
                    >
                      <span className="text-muted">
                        {ROLE[participant.role] ?? participant.role}
                      </span>
                      <SubjectLink subject={participant.subject} onSelect={onSelect} />
                      {participant.parameter_key ? (
                        <span className="mono">
                          {participant.parameter_key} = {formatValue(participant.value ?? null)}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </InspectorSection>
  </section>
);
