'use client';

import type { SheetRead } from '@quantor/api-client';
import Link from 'next/link';
import type { FC } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import { pageLabel } from '@/lib/cad/format';
import type { ISheetResult } from '@/lib/cad/sheet-results';
import { CALIBRATION_UNAVAILABLE_TEXT, type SheetCalibrationState } from '@/lib/cad/sheets';

interface ICadSheetRowProps {
  sheet: SheetRead;
  href: string;
  state: SheetCalibrationState;
  manualEnabled: boolean;
  checked: boolean;
  limitReached: boolean;
  /** Последнее задание по листу; `null` — листа в заданиях ещё не было. */
  result: ISheetResult | null;
  /** Этот лист сейчас открыт в рабочей области. */
  open: boolean;
  onToggle: () => void;
  /** Открыть лист в рабочей области (с результатом или без). */
  onOpen: () => void;
}

/**
 * Строка листа. Текст строки открывает лист в рабочей области (с результатом CAD, если он есть),
 * а чекбокс остаётся отдельной тап-целью выбора для запуска преобразования.
 */
export const CadSheetRow: FC<ICadSheetRowProps> = ({
  sheet,
  href,
  state,
  manualEnabled,
  checked,
  limitReached,
  result,
  open,
  onToggle,
  onOpen,
}) => {
  const extraLabel =
    sheet.page_label && sheet.page_label !== String(sheet.page_index + 1) ? sheet.page_label : null;
  const title = (
    <span className="[overflow-wrap:anywhere]">
      {pageLabel(sheet.page_index)}
      {extraLabel && <span className="text-muted"> · {extraLabel}</span>}
    </span>
  );
  const checkbox = (
    <input
      type="checkbox"
      checked={checked}
      disabled={!checked && limitReached}
      onChange={onToggle}
      aria-label={pageLabel(sheet.page_index)}
      className="h-[18px] w-[18px] shrink-0 accent-accent"
    />
  );

  return (
    <li
      className={cx(
        'flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] last:border-b-0',
        (checked || open) && 'bg-accent-soft',
        open && 'shadow-[inset_3px_0_0_var(--accent)]',
      )}
    >
      <label className="-ml-[var(--s-3)] flex h-[44px] w-[44px] shrink-0 cursor-pointer items-center justify-center">
        {checkbox}
      </label>
      <button
        type="button"
        onClick={onOpen}
        aria-current={open ? 'true' : undefined}
        className="flex min-h-[44px] min-w-0 flex-1 flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)] text-left text-sm hover:text-accent"
      >
        {title}
        {result && <ResultBadge result={result} />}
      </button>

      {state === 'calibrated' && (
        <StatusBadge tone="success" dot={false}>
          Калибровка есть
        </StatusBadge>
      )}
      {state === 'loading' && <span className="text-xs text-muted">Проверка калибровки…</span>}
      {checked && state === 'unknown' && !manualEnabled && (
        <span className="text-xs text-muted">Калибровка не проверена</span>
      )}
      {checked && state === 'unknown' && manualEnabled && (
        <span className="text-xs text-muted">Калибровка не прочитана</span>
      )}
      {state === 'missing' && (
        <>
          <StatusBadge tone="warning" dot={false}>
            Нет калибровки
          </StatusBadge>
          {manualEnabled ? (
            <Link
              href={href}
              target="_blank"
              rel="noopener"
              className="inline-flex min-h-[44px] items-center text-xs text-accent underline underline-offset-4"
            >
              Откалибровать
            </Link>
          ) : (
            <span className="text-xs text-muted">{CALIBRATION_UNAVAILABLE_TEXT}</span>
          )}
        </>
      )}
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
