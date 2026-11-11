'use client';

import { recomputeCadWalls } from '@quantor/api-client';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, type FC } from 'react';

import { Button } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import { cadPipelineKey } from '@/lib/cad/pipeline-queries';
import { unwrap } from '@/lib/queries';

export interface IWorkspaceCadWallsRetryProps {
  readonly projectId: string;
  readonly revisionId: string;
  /** Задание преобразования листа (`cad_pdf_convert`), родитель расчёта конструкций. */
  readonly jobId: string;
  readonly pageIndex: number;
  /** Виды листа, у которых последнее задание `cad_walls` упало. */
  readonly views: readonly number[];
}

/**
 * Кнопка «Повторить» у упавшего шага «Конструкции»: пересчёт конструкций по каждому упавшему виду.
 * Сервер не блокирует пересчёт после упавшего задания; идущий расчёт отвечает 409 `CAD_WALLS_BUSY`.
 */
export const WorkspaceCadWallsRetry: FC<IWorkspaceCadWallsRetryProps> = ({
  projectId,
  revisionId,
  jobId,
  pageIndex,
  views,
}) => {
  const client = useQueryClient();
  // Синхронная защита от двойного нажатия: isPending обновляется после рендера.
  const launching = useRef(false);
  const retry = useMutation({
    mutationFn: async () => {
      await Promise.all(
        views.map(async (view) =>
          unwrap(
            await recomputeCadWalls({
              throwOnError: true,
              path: { project_id: projectId, job_id: jobId, page_index: pageIndex, view },
            }),
          ),
        ),
      );
    },
    onSettled: () => {
      launching.current = false;
      void client.invalidateQueries({ queryKey: ['cad-constructions', projectId, revisionId] });
      void client.invalidateQueries({ queryKey: cadPipelineKey(projectId, revisionId) });
    },
  });

  const run = () => {
    if (launching.current || retry.isPending || views.length === 0) return;
    launching.current = true;
    retry.mutate();
  };

  return (
    <div className="flex min-w-0 flex-col items-start gap-[var(--s-2)]">
      <Button
        variant="primary"
        compact
        loading={retry.isPending}
        onClick={run}
        className="self-start max-md:h-[44px] max-md:w-full"
      >
        Повторить
      </Button>
      {retry.isError && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {cadErrorText(retry.error)}
        </p>
      )}
    </div>
  );
};
