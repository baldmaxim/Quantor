'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useEffect, type FC } from 'react';

import { Button, StatusBadge } from '@/components/ui';
import { extractCode } from '@/lib/errors';
import { useModelImport, useStartModelImport } from '@/lib/model/model-queries';
import { importActive, importErrorText, importView } from '@/lib/model/model-versions';

interface IModelImportPanelProps {
  readonly projectId: string;
}

/**
 * «Модель из IFC»: портал сам читает IFC, загруженные в проект обычными документами, и строит
 * модель кандидатом (задание `model_ifc_import`). Когда задание готово, список версий обновляется.
 */
export const ModelImportPanel: FC<IModelImportPanelProps> = ({ projectId }) => {
  const queryClient = useQueryClient();
  const job = useModelImport(projectId, true);
  const start = useStartModelImport(projectId);
  const current = job.data ?? null;
  const status = current?.status ?? null;
  const busy = start.isPending || importActive(status);

  useEffect(() => {
    if (status === 'succeeded') {
      void queryClient.invalidateQueries({ queryKey: ['model', projectId] });
    }
  }, [status, projectId, queryClient]);

  const view = status === null ? null : importView(status);
  return (
    <div
      className="flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted"
      data-testid="model-import"
    >
      <Button
        variant="primary"
        disabled={busy}
        onClick={() => start.mutate()}
        className="self-start max-md:h-[44px] max-md:w-full"
      >
        {status === 'succeeded' ? 'Перестроить модель из IFC' : 'Построить модель из IFC'}
      </Button>
      {view !== null && current !== null && (
        <p role="status" className="flex flex-wrap items-center gap-[var(--s-2)]">
          <StatusBadge tone={view.tone}>{view.label}</StatusBadge>
          <span>
            IFC: {current.inputs}
            {current.generator_version ? ` · ${current.generator_version}` : ''}
          </span>
        </p>
      )}
      {status === 'failed' && current?.error_message && (
        <p role="alert" className="text-[var(--danger)]">
          {current.error_message}
        </p>
      )}
      {start.isError && (
        <p role="alert" className="text-[var(--danger)]">
          {importErrorText(extractCode(start.error))}
        </p>
      )}
    </div>
  );
};
