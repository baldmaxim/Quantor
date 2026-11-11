'use client';

import type { SheetRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import { pageLabel } from '@/lib/cad/format';
import type { ISheetResult } from '@/lib/cad/sheet-results';
import type { SheetCalibrationState } from '@/lib/cad/sheets';

interface ICadSheetRowProps {
  sheet: SheetRead;
  /** Известна только у открытого листа: у остальных `unknown`, и бейджа нет. */
  state: SheetCalibrationState;
  /** Последнее задание по листу; `null` — листа в заданиях ещё не было. */
  result: ISheetResult | null;
  /** Этот лист сейчас открыт в рабочей области. */
  open: boolean;
  /** Открыть лист в рабочей области (с результатом или без). */
  onOpen: () => void;
}

/**
 * Строка листа: вся строка - одна кнопка, открывающая лист в рабочей области (с результатом CAD,
 * если он есть). Калибровка - кнопкой «Откалибровать» у преобразования листа, не здесь.
 */
export const CadSheetRow: FC<ICadSheetRowProps> = ({ sheet, state, result, open, onOpen }) => {
  const extraLabel =
    sheet.page_label && sheet.page_label !== String(sheet.page_index + 1) ? sheet.page_label : null;

  return (
    <li
      className={cx(
        'flex flex-col border-b border-border last:border-b-0',
        open && 'bg-accent-soft shadow-[inset_3px_0_0_var(--accent)]',
      )}
    >
      <button
        type="button"
        onClick={onOpen}
        aria-current={open ? 'true' : undefined}
        className="flex min-h-[44px] w-full min-w-0 flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)] px-[var(--s-5)] py-[var(--s-2)] text-left text-sm hover:text-accent"
      >
        <span className="max-w-full truncate whitespace-nowrap">
          {pageLabel(sheet.page_index)}
          {extraLabel && <span className="text-muted"> · {extraLabel}</span>}
        </span>
        {result && <ResultBadge result={result} />}
        {state === 'calibrated' && (
          <StatusBadge tone="success" dot={false}>
            Калибровка есть
          </StatusBadge>
        )}
        {state === 'missing' && (
          <StatusBadge tone="warning" dot={false}>
            Нет калибровки
          </StatusBadge>
        )}
      </button>
    </li>
  );
};

const ResultBadge: FC<{ result: ISheetResult }> = ({ result }) => {
  if (result.kind === 'running') {
    return (
      <StatusBadge tone="accent" dot={false}>
        Выполняется
      </StatusBadge>
    );
  }
  if (result.kind === 'failed') {
    return (
      <StatusBadge tone="danger" dot={false}>
        Ошибка
      </StatusBadge>
    );
  }
  return (
    <StatusBadge tone="warning" dot={false}>
      {result.dxf ? 'DXF есть · проверка' : 'Только диагностика'}
    </StatusBadge>
  );
};
