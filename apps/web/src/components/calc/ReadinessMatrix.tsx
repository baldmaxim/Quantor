'use client';

import type { CalcFactTypeRead, CalcReadinessRead } from '@quantor/api-client';
import { useState } from 'react';

import { ReadinessTable } from '@/components/calc/ReadinessTable';
import { cx } from '@/components/ui';
import { LEVEL_TITLES } from '@/lib/calc/format';

/**
 * Готовность исходных данных к расчёту по системам.
 *
 * Счётчики — по уровням, а не общим процентом: закрытые дополнительные данные не должны
 * маскировать незакрытые обязательные. «Закрыто» — найдено или выводимо из найденного.
 */

interface IReadinessMatrixProps {
  readiness: CalcReadinessRead;
  factTypes: ReadonlyMap<string, CalcFactTypeRead>;
}

export const ReadinessMatrix = ({ readiness, factTypes }: IReadinessMatrixProps) => {
  const [selected, setSelected] = useState(readiness.systems[0]?.system_code ?? '');
  const current =
    readiness.systems.find((item) => item.system_code === selected) ?? readiness.systems[0];
  const documents = readiness.documents;

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <p className="text-sm text-muted">
        Распознанных документов: {documents.recognized}, проверено: {documents.inspected}
        {documents.not_inspected > 0 && `, ещё не проверено: ${documents.not_inspected}`}
        {documents.without_recognition > 0 &&
          `; без распознанного текста: ${documents.without_recognition}`}
        .
      </p>

      <div className="grid gap-[var(--s-4)] sm:grid-cols-2 xl:grid-cols-4">
        {readiness.systems.map((system) => {
          const active = system.system_code === current?.system_code;
          return (
            <button
              key={system.system_code}
              type="button"
              aria-pressed={active}
              onClick={() => setSelected(system.system_code)}
              className={cx(
                'press flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border bg-surface p-[var(--s-5)] text-left',
                'transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:bg-surface-muted',
                active
                  ? 'border-accent shadow-[0_0_0_3px_var(--accent-soft)]'
                  : 'border-border-strong',
              )}
            >
              <span className="text-sm font-medium">
                {system.system_code}
                <span className="font-normal text-muted"> — {system.title}</span>
              </span>
              <span className="grid grid-cols-[1fr_auto] gap-x-[var(--s-5)] text-xs">
                {system.counts.map((count) => (
                  <span key={count.level} className="contents">
                    <span className="text-muted">{LEVEL_TITLES[count.level]}</span>
                    <span className="tabular">
                      {count.satisfied}/{count.total}
                    </span>
                  </span>
                ))}
              </span>
            </button>
          );
        })}
      </div>

      {current && <ReadinessTable rows={current.rows} factTypes={factTypes} />}
    </div>
  );
};
