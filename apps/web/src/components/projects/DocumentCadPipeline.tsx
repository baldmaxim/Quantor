'use client';

import { useCallback, useMemo, useState, type FC } from 'react';

import { EmptyState, ErrorState, Skeleton } from '@/components/ui';
import { sheetRows } from '@/lib/cad/pipeline-actions';
import { isPipelineSelectable } from '@/lib/cad/pipeline-batch';
import { useCadPipeline } from '@/lib/cad/pipeline-queries';
import { sheetPosition } from '@/lib/cad/workspace-url';
import { useSheets } from '@/lib/queries';

import { CadBulkLaunchBar, type IBulkLaunchFailureView } from './CadBulkLaunchBar';
import { CadPipelineSheetRow } from './CadPipelineSheetRow';
import { useBulkPipelineRun } from './useBulkPipelineRun';

/**
 * Конвейер CAD по листам одной ревизии (планы и листы с работой, по порядку страниц);
 * опрашивается, пока что-то идёт. Над списком - массовый запуск конвейера по шагам, которые не отработаны.
 */
export const DocumentCadPipeline: FC<{
  readonly projectId: string;
  readonly revisionId: string;
}> = ({ projectId, revisionId }) => {
  const pipeline = useCadPipeline(projectId, revisionId, true);
  const sheets = useSheets(revisionId);
  const known = useMemo(() => sheets.data?.items ?? [], [sheets.data]);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());

  const ordered = useMemo(
    () => [...(pipeline.data?.sheets ?? [])].sort((a, b) => a.page_index - b.page_index),
    [pipeline.data],
  );
  const positionOf = useCallback(
    (pageIndex: number) => sheetPosition(known, pageIndex) ?? pageIndex + 1,
    [known],
  );
  const bulk = useBulkPipelineRun(
    projectId,
    revisionId,
    ordered,
    pipeline.dataUpdatedAt,
    positionOf,
  );
  // Выбираемы листы, где можно запустить преобразование или есть следующий машинный шаг.
  const launchable = useMemo(
    () =>
      ordered
        .filter((sheet) =>
          isPipelineSelectable(
            sheet,
            sheetRows(projectId, revisionId, positionOf(sheet.page_index), sheet),
          ),
        )
        .map((sheet) => sheet.page_index),
    [ordered, projectId, revisionId, positionOf],
  );
  const launchableSet = useMemo(() => new Set(launchable), [launchable]);
  // Выбор переживает обновления конвейера, но лист, ставший недоступным, из него выпадает.
  const effective = useMemo(
    () => launchable.filter((pageIndex) => selected.has(pageIndex)),
    [launchable, selected],
  );

  if (pipeline.isPending) return <Skeleton className="h-[96px] w-full" />;

  if (pipeline.isError) {
    return (
      <ErrorState
        title="Не удалось получить состояние CAD"
        onRetry={() => void pipeline.refetch()}
      />
    );
  }

  if (ordered.length === 0) {
    return (
      <EmptyState
        compact
        title="Листов для CAD нет"
        description="В документе не найдено листов со словом „План“ в названии и листов с работой CAD"
      />
    );
  }

  const plans = ordered.filter((sheet) => sheet.is_plan);
  const labelOf = (pageIndex: number): string => {
    const sheet = ordered.find((row) => row.page_index === pageIndex);
    return `Лист ${sheet?.page_label ?? pageIndex + 1}`;
  };
  const failures: IBulkLaunchFailureView[] = bulk.failures.map((failure) => ({
    ...failure,
    label: labelOf(failure.pageIndex),
  }));

  const toggleOne = (pageIndex: number, checked: boolean) =>
    setSelected((previous) => {
      const next = new Set(previous);
      if (checked) next.add(pageIndex);
      else next.delete(pageIndex);
      return next;
    });

  const toggleAll = (checked: boolean) => setSelected(new Set(checked ? launchable : []));

  const launch = () => {
    bulk.start(effective);
    setSelected(new Set());
  };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
      <CadBulkLaunchBar
        plansCount={plans.length}
        withoutCadCount={plans.filter((sheet) => sheet.convert === null).length}
        launchableCount={launchable.length}
        selectedCount={effective.length}
        running={bulk.running}
        total={bulk.total}
        finished={bulk.finished}
        failures={failures}
        onToggleAll={toggleAll}
        onLaunch={launch}
        onStop={bulk.stop}
      />
      <ul className="m-0 list-none p-0" aria-label="Листы CAD">
        {ordered.map((sheet) => (
          <CadPipelineSheetRow
            key={sheet.page_index}
            projectId={projectId}
            revisionId={revisionId}
            sheet={sheet}
            position={positionOf(sheet.page_index)}
            selected={selected.has(sheet.page_index) && launchableSet.has(sheet.page_index)}
            selectable={launchableSet.has(sheet.page_index) && !bulk.running}
            onSelectedChange={(checked) => toggleOne(sheet.page_index, checked)}
          />
        ))}
      </ul>
    </div>
  );
};
