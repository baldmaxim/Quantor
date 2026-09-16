'use client';

import type { BoqStatus, MepScenarioRead, QuantityBlocker } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import { classLabel, type MepSelection } from '@/lib/mep/trace';

import { BoqLineDetail, SubjectLink } from './BoqLineDetail';
import { Panel, formatValue } from './parts';

interface IBoqTableProps {
  readonly scenario: MepScenarioRead;
  readonly selectedLineId: string | null;
  readonly onSelect: (selection: MepSelection) => void;
}

const STATUS: Readonly<
  Record<BoqStatus, { tone: 'success' | 'warning' | 'danger'; label: string }>
> = {
  complete: { tone: 'success', label: 'рассчитан полностью' },
  partial: { tone: 'warning', label: 'рассчитан частично' },
  refused: { tone: 'danger', label: 'расчёт отказан' },
};

const UNIT: Readonly<Record<string, string>> = { m: 'м', pcs: 'шт' };

/** Ссылки блокера: типизированные — по виду, остальные id показываются как есть, без перехода. */
const BlockerSubjects: FC<{
  readonly item: QuantityBlocker;
  readonly onSelect: (selection: MepSelection) => void;
}> = ({ item, onSelect }) => {
  const typed = new Set((item.subjects ?? []).map((ref) => ref.id));
  return (
    <>
      {(item.subjects ?? []).map((ref) => (
        <SubjectLink key={`${ref.kind}:${ref.id}`} subject={ref} onSelect={onSelect} />
      ))}
      {(item.subject_ids ?? [])
        .filter((id) => !typed.has(id))
        .map((id) => (
          <span key={id} className="mono text-muted" title="вид объекта не указан">
            {id}
          </span>
        ))}
    </>
  );
};

/** Шаг 3: физический ВОР, посчитанный движком на сервере. Интерфейс чисел не вычисляет. */
export const BoqTable: FC<IBoqTableProps> = ({ scenario, selectedLineId, onSelect }) => {
  const boq = scenario.boq;
  const status = STATUS[boq.status];
  const blockers = (boq.blockers ?? []).filter((item) => item.severity === 'blocker');
  const warnings = (boq.blockers ?? []).filter((item) => item.severity === 'warning');
  const graphErrors = scenario.network_issues.filter((issue) => issue.severity === 'error');
  const selected = boq.lines.find((line) => line.line_id === selectedLineId);

  return (
    <Panel
      title="Физический ВОР · Calculated Takeoff"
      aside={<StatusBadge tone={status.tone}>{status.label}</StatusBadge>}
    >
      <p className="text-xs text-muted">
        Количества из сети РД по правилам {boq.engine.name} {boq.engine.version}, режим {boq.lane}.
        Это не ВОР заказчика: фитинги, крепления, изоляция, монтажные комплекты, коэффициенты и цены
        не рассчитываются.
      </p>

      <div className="scroll-area overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th className="py-[var(--s-3)] pr-[var(--s-4)] font-medium">Правило</th>
              <th className="py-[var(--s-3)] pr-[var(--s-4)] font-medium">Класс</th>
              <th className="py-[var(--s-3)] pr-[var(--s-4)] font-medium">Группа</th>
              <th className="py-[var(--s-3)] pr-[var(--s-4)] text-right font-medium">Кол-во</th>
              <th className="py-[var(--s-3)] pr-[var(--s-4)] font-medium">Ед.</th>
              <th className="py-[var(--s-3)] pr-[var(--s-4)] font-medium">Источники · вклад</th>
              <th className="py-[var(--s-3)] font-medium">Статус строки</th>
            </tr>
          </thead>
          <tbody>
            {boq.lines.map((line) => (
              <tr
                key={line.line_id}
                aria-selected={line.line_id === selectedLineId}
                className={cx(
                  'cursor-pointer border-b border-border align-top',
                  line.line_id === selectedLineId ? 'bg-accent-soft' : 'hover:bg-surface-muted',
                )}
                onClick={() => onSelect({ kind: 'line', id: line.line_id })}
              >
                <td className="mono py-[var(--s-3)] pr-[var(--s-4)] text-xs">{line.rule_id}</td>
                <td className="py-[var(--s-3)] pr-[var(--s-4)]">
                  {line.class_key ? classLabel(scenario, line.class_key) : '—'}
                </td>
                <td className="py-[var(--s-3)] pr-[var(--s-4)] text-xs">
                  {(line.group ?? [])
                    .map((item) => `${item.key} = ${formatValue(item.value, item.unit)}`)
                    .join('; ') || '—'}
                </td>
                <td className="tabular py-[var(--s-3)] pr-[var(--s-4)] text-right">
                  {line.quantity}
                </td>
                <td className="py-[var(--s-3)] pr-[var(--s-4)]">{UNIT[line.unit] ?? line.unit}</td>
                <td
                  className="py-[var(--s-3)] pr-[var(--s-4)]"
                  onClick={(event) => event.stopPropagation()}
                >
                  <span className="flex flex-col gap-[var(--s-2)]">
                    {(line.sources ?? []).map((source) => (
                      <span key={source.subject.id} className="flex items-center gap-[var(--s-2)]">
                        <SubjectLink subject={source.subject} onSelect={onSelect} />
                        {source.quantity !== null && source.quantity !== undefined ? (
                          <span className="tabular text-xs text-muted">{source.quantity}</span>
                        ) : null}
                      </span>
                    ))}
                  </span>
                </td>
                <td className="py-[var(--s-3)]">
                  {line.review_required ? (
                    <StatusBadge tone="warning">review_required</StatusBadge>
                  ) : (
                    <StatusBadge tone="success">без выведенного</StatusBadge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {boq.lines.length === 0 && <p className="py-[var(--s-4)] text-sm text-muted">Строк нет.</p>}
      </div>

      {selected ? <BoqLineDetail line={selected} onSelect={onSelect} /> : null}

      {[
        { title: 'Блокеры', items: blockers, tone: 'text-danger' },
        { title: 'Предупреждения', items: warnings, tone: 'text-warning' },
      ].map(
        ({ title, items, tone }) =>
          items.length > 0 && (
            <section key={title} aria-label={title} className="flex flex-col gap-[var(--s-2)]">
              <h3 className="text-xs font-medium text-muted">{title}</h3>
              <ul className="flex flex-col gap-[var(--s-2)] text-xs">
                {items.map((item) => (
                  <li
                    key={`${item.code}:${(item.subject_ids ?? []).join(',')}:${item.key ?? ''}`}
                    className="flex flex-wrap items-center gap-[var(--s-3)]"
                  >
                    <span className={cx('mono', tone)}>{item.code}</span>
                    {item.key ? <span className="mono text-muted">{item.key}</span> : null}
                    <span>{item.message}</span>
                    <BlockerSubjects item={item} onSelect={onSelect} />
                  </li>
                ))}
              </ul>
            </section>
          ),
      )}
      {boq.status === 'refused' && graphErrors.length > 0 && (
        <section aria-label="Проверка графа" className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-xs font-medium text-muted">Проверка графа: почему расчёт отказан</h3>
          <ul className="flex flex-col gap-[var(--s-2)] text-xs">
            {graphErrors.map((issue) => (
              <li
                key={`${issue.code}:${issue.subject_id ?? ''}`}
                className="flex flex-wrap gap-[var(--s-3)]"
              >
                <span className="mono text-danger">{issue.code}</span>
                <span className="mono text-muted">{issue.subject_id ?? '—'}</span>
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {(scenario.boq_issues ?? []).length > 0 && (
        <p role="alert" className="text-xs text-danger">
          Ссылки ВОР не сходятся с сетью:{' '}
          {scenario.boq_issues.map((issue) => issue.code).join(', ')}
        </p>
      )}
    </Panel>
  );
};
