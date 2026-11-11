'use client';

import type { FC } from 'react';

import { Button, Skeleton } from '@/components/ui';

import { ConstructionsLevels } from './ConstructionsLevels';
import { ConstructionsTotals } from './ConstructionsTotals';
import { ConstructionsVor } from './ConstructionsVor';
import type { IWorkspaceCadConstructions } from './types';

/**
 * Раздел «Конструкции»: свод кладки и монолита листа (ADR-0038). Нет результата расчёта - текст по
 * статусу задания и кнопка «Посчитать конструкции»; пока задание идёт, панель сама опрашивает сервер.
 * Величины считает сервер; «не определено» показывается текстом, а не нулём.
 */
export const ConstructionsPanel: FC<IWorkspaceCadConstructions> = ({
  status,
  data,
  notReadyText,
  loadError,
  onReload,
  calculating,
  actionError,
  recomputeFailure = null,
  onCompute,
  levelsSaving,
  onSaveLevels,
  activeGroup,
  onSelectGroup,
  vor,
}) => {
  if (status === 'loading') {
    return (
      <div role="status" aria-label="Загрузка конструкций" className="flex flex-col gap-[var(--s-3)]">
        <Skeleton className="h-[20px] w-[60%]" />
        <Skeleton className="h-[16px] w-[80%]" />
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div role="alert" className="flex flex-col gap-[var(--s-3)] text-xs text-danger">
        <span>Не удалось загрузить конструкции. {loadError}</span>
        <Button compact className="self-start max-md:h-[44px]" onClick={onReload}>
          Повторить
        </Button>
      </div>
    );
  }

  const action = (label: string, variant: 'primary' | 'default') => (
    <Button
      variant={variant}
      disabled={calculating}
      className="self-start max-md:h-[44px]"
      onClick={onCompute}
    >
      {label}
    </Button>
  );

  const calculatingNote = calculating && (
    <p role="status" className="text-xs text-muted">
      {data === null
        ? 'Конструкции считаются. Результат появится здесь сам.'
        : 'Пересчёт идёт…'}
    </p>
  );
  // Показан прежний результат, а свежий пересчёт упал: об этом сказано заметно.
  const recomputeFailed = !calculating && recomputeFailure !== null && (
    <p
      role="alert"
      data-testid="constructions-recompute-failed"
      className="rounded-md border border-danger px-[var(--s-3)] py-[var(--s-2)] text-xs text-danger"
    >
      Пересчёт не удался: {recomputeFailure}
    </p>
  );
  const failure = actionError !== null && (
    <p role="alert" className="text-xs text-danger">
      {actionError}
    </p>
  );

  if (status === 'not-ready' || data === null) {
    return (
      <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="constructions-not-ready">
        {!calculating && <p className="text-xs text-muted">{notReadyText}</p>}
        {calculatingNote}
        {failure}
        {action('Посчитать конструкции', 'primary')}
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-6)]" data-testid="constructions-panel">
      <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
        <p className="text-xs text-muted">
          Конструкций на листе: <span className="text-text">{data.summary.total_count}</span>
        </p>
        {calculatingNote}
        {recomputeFailed}
        {failure}
        {action('Пересчитать', 'default')}
      </div>
      <ConstructionsLevels
        // Значения высот пришли другими (сохранение, пересчёт): поля начинаются заново.
        key={JSON.stringify(data.sheet_levels)}
        data={data}
        saving={levelsSaving}
        onSave={onSaveLevels}
      />
      <ConstructionsTotals data={data} activeGroup={activeGroup} onSelectGroup={onSelectGroup} />
      {vor && <ConstructionsVor vor={vor} />}
    </div>
  );
};
