'use client';

import type { FC } from 'react';

import { EmptyState, ErrorState, Skeleton } from '@/components/ui';
import { useCadPipeline } from '@/lib/cad/pipeline-queries';
import { sheetPosition } from '@/lib/cad/workspace-url';
import { useSheets } from '@/lib/queries';

import { CadPipelineSheetRow } from './CadPipelineSheetRow';

/** Конвейер CAD по листам одной ревизии; опрашивается, пока что-то идёт. */
export const DocumentCadPipeline: FC<{ readonly projectId: string; readonly revisionId: string }> = ({
  projectId,
  revisionId,
}) => {
  const pipeline = useCadPipeline(projectId, revisionId, true);
  const sheets = useSheets(revisionId);
  const known = sheets.data?.items ?? [];

  if (pipeline.isPending) return <Skeleton className="h-[96px] w-full" />;

  if (pipeline.isError) {
    return (
      <ErrorState
        title="Не удалось получить состояние CAD"
        onRetry={() => void pipeline.refetch()}
      />
    );
  }

  if (pipeline.data.sheets.length === 0) {
    return (
      <EmptyState
        compact
        title="Листов в CAD пока нет"
        description="Листы ещё не обрабатывались: откройте документ, откалибруйте лист и запустите преобразование в CAD."
      />
    );
  }

  return (
    <ul className="m-0 list-none p-0" aria-label="Листы CAD">
      {pipeline.data.sheets.map((sheet) => (
        <CadPipelineSheetRow
          key={sheet.page_index}
          projectId={projectId}
          revisionId={revisionId}
          sheet={sheet}
          position={sheetPosition(known, sheet.page_index) ?? sheet.page_index + 1}
        />
      ))}
    </ul>
  );
};
