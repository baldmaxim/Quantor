'use client';

import type { CadScaleControlRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import { formatInt, formatNumber, NO_VALUE } from '@/lib/cad/view-format';

interface ICadControlsTableProps {
  controls: readonly CadScaleControlRead[];
}

const ROLE_LABELS: Readonly<Record<string, string>> = {
  fit: 'подбор (fit)',
  holdout: 'проверка (holdout)',
  heldout: 'проверка (holdout)',
};

const TH = 'whitespace-nowrap px-[var(--s-4)] py-[var(--s-3)] text-left font-medium text-muted';
const TD = 'tabular whitespace-nowrap px-[var(--s-4)] py-[var(--s-3)]';

/**
 * Контроли масштаба. Таблица шире экрана телефона: прокручивается своим контейнером, страница
 * в целом по горизонтали не едет.
 */
export const CadControlsTable: FC<ICadControlsTableProps> = ({ controls }) => {
  if (controls.length === 0) {
    return <p className="text-xs text-muted">Размерных цепочек для контроля не найдено.</p>;
  }

  return (
    <div
      className="scroll-area max-w-full overflow-x-auto overscroll-x-contain rounded-[var(--radius-md)] border border-border"
      tabIndex={0}
      role="region"
      aria-label="Контроли масштаба"
    >
      <table className="w-full min-w-[620px] border-collapse text-xs">
        <thead className="bg-surface-muted">
          <tr>
            <th className={TH}>Цепочка</th>
            <th className={TH}>Роль</th>
            <th className={TH}>Подпись, мм</th>
            <th className={TH}>По масштабу, мм</th>
            <th className={TH}>Невязка, мм</th>
            <th className={TH}>Допуск, мм</th>
            <th className={TH}>В допуске</th>
          </tr>
        </thead>
        <tbody>
          {controls.map((control, index) => (
            <tr key={`${control.chain_id ?? 'n'}-${index}`} className="border-t border-border">
              <td className={TD}>{control.chain_id === null ? NO_VALUE : formatInt(control.chain_id)}</td>
              <td className={TD}>{ROLE_LABELS[control.role] ?? (control.role || NO_VALUE)}</td>
              <td className={TD}>{formatNumber(control.label_mm, 1)}</td>
              <td className={TD}>{formatNumber(control.fitted_measured_mm, 1)}</td>
              <td className={TD}>{formatNumber(control.residual_mm, 2)}</td>
              <td className={TD}>{formatNumber(control.tolerance_mm, 2)}</td>
              <td className={TD}>
                {control.within_tolerance === null ? (
                  NO_VALUE
                ) : (
                  <StatusBadge tone={control.within_tolerance ? 'success' : 'danger'} dot={false}>
                    {control.within_tolerance ? '✓ да' : '✗ нет'}
                  </StatusBadge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
