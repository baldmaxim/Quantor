'use client';

import { useEffect, useId, useRef, type FC } from 'react';

import { Button } from '@/components/ui';

/**
 * Панель массового запуска преобразования в CAD над списком листов: сводка, «выбрать все
 * доступные», кнопка запуска и ход очереди. Только рисует; выбор и очередь - у родителя.
 * Узкий экран - колонкой, без горизонтальной прокрутки.
 */

export interface IBulkLaunchFailureView {
  readonly pageIndex: number;
  /** Подпись листа: «Лист 3». */
  readonly label: string;
  readonly message: string;
}

export interface ICadBulkLaunchBarProps {
  /** Листов-планов в ревизии. */
  readonly plansCount: number;
  /** Из них без преобразования в CAD. */
  readonly withoutCadCount: number;
  /** Листов, доступных к запуску (чекбокс активен). */
  readonly launchableCount: number;
  readonly selectedCount: number;
  readonly running: boolean;
  /** Размер текущей очереди и сколько принято сервером; показываются, пока очередь идёт. */
  readonly total: number;
  readonly placed: number;
  readonly failures: readonly IBulkLaunchFailureView[];
  readonly onToggleAll: (checked: boolean) => void;
  readonly onLaunch: () => void;
}

export const CadBulkLaunchBar: FC<ICadBulkLaunchBarProps> = ({
  plansCount,
  withoutCadCount,
  launchableCount,
  selectedCount,
  running,
  total,
  placed,
  failures,
  onToggleAll,
  onLaunch,
}) => {
  const checkId = useId();
  const checkRef = useRef<HTMLInputElement>(null);
  const allSelected = launchableCount > 0 && selectedCount >= launchableCount;
  const partial = selectedCount > 0 && !allSelected;

  // `indeterminate` задаётся только свойством элемента.
  useEffect(() => {
    if (checkRef.current) checkRef.current.indeterminate = partial;
  }, [partial]);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)] border-b border-border pb-[var(--s-4)]">
      <p className="m-0 text-sm text-muted">{`Планов: ${plansCount} · без CAD: ${withoutCadCount}`}</p>
      <div className="flex min-w-0 flex-col gap-[var(--s-3)] md:flex-row md:items-center md:justify-between">
        <label
          htmlFor={checkId}
          className="flex min-h-[44px] min-w-0 cursor-pointer items-center gap-[var(--s-3)] text-sm"
        >
          <input
            ref={checkRef}
            id={checkId}
            type="checkbox"
            checked={allSelected}
            disabled={launchableCount === 0 || running}
            onChange={(event) => onToggleAll(event.target.checked)}
            className="size-5 flex-none accent-accent"
          />
          Выбрать все доступные
        </label>
        <Button
          variant="primary"
          compact
          loading={running}
          loadingLabel="Запуск…"
          disabled={selectedCount === 0 || running}
          onClick={onLaunch}
          className="max-md:h-[44px] max-md:w-full"
        >
          {`Преобразовать выбранные (${selectedCount})`}
        </Button>
      </div>
      {running && (
        <p role="status" className="m-0 text-xs text-muted">
          {`Поставлено ${placed} из ${total}`}
        </p>
      )}
      {!running && failures.length > 0 && (
        <div role="alert" className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <p className="m-0 text-xs text-danger">
            {`Поставлено ${placed} из ${total}; не поставлено: ${failures.length}`}
          </p>
          <ul className="m-0 list-none p-0">
            {failures.map((failure) => (
              <li
                key={failure.pageIndex}
                className="text-xs text-danger [overflow-wrap:anywhere]"
              >
                {`${failure.label}: ${failure.message}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
