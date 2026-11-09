'use client';

import type { CadJobRead } from '@quantor/api-client';
import { useMemo, type FC } from 'react';

import { EmptyState, ErrorState, Skeleton } from '@/components/ui';
import { cadViewErrorText, useCadView, type ICadViewParams } from '@/lib/cad/view-queries';

import { CadChecksSection } from './CadChecksSection';
import { CadFilesSection } from './CadFilesSection';
import { CadScaleSection } from './CadScaleSection';
import { CadViewHeader } from './CadViewHeader';
import { CadViewerPane } from './CadViewerPane';

interface ICadViewPanelProps {
  projectId: string;
  revisionId: string;
  job: CadJobRead;
  pageIndex: number;
  view: number;
}

/**
 * Панель вида результата CAD: диагностика, PDF с наложением CAD, файлы.
 *
 * Показывает только результат попытки `result_attempt`. Нет результата - нет и панели:
 * файлы и геометрия других попыток сюда не подмешиваются.
 */
export const CadViewPanel: FC<ICadViewPanelProps> = ({
  projectId,
  revisionId,
  job,
  pageIndex,
  view,
}) => {
  const attempt = job.result_attempt;
  const params = useMemo<ICadViewParams | null>(
    () =>
      attempt === null
        ? null
        : { projectId, revisionId, jobId: job.job_id, attempt, pageIndex, view },
    [projectId, revisionId, job.job_id, attempt, pageIndex, view],
  );

  if (params === null) {
    return <EmptyState compact title="Результат попытки ещё не готов" />;
  }

  return <CadViewBody key={paramsKey(params)} params={params} />;
};

const paramsKey = (params: ICadViewParams): string =>
  [
    params.projectId,
    params.revisionId,
    params.jobId,
    params.attempt,
    params.pageIndex,
    params.view,
  ].join(':');

/** Отдельный компонент под ключ: при смене вида сбрасываются камеры, слои и выбранный режим. */
const CadViewBody: FC<{ params: ICadViewParams }> = ({ params }) => {
  const query = useCadView(params);

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-[var(--s-4)]" role="status" aria-label="Загрузка вида">
        <Skeleton className="h-[20px] w-[60%]" />
        <Skeleton className="h-[16px] w-[80%]" />
        <Skeleton className="h-[240px] w-full" />
      </div>
    );
  }

  if (query.isError) {
    const { code, text } = cadViewErrorText(query.error);
    return (
      <ErrorState
        title="Диагностика вида не загружена"
        code={code}
        description={text}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const diagnostics = query.data;

  return (
    <article className="flex min-w-0 flex-col gap-[var(--s-6)]">
      <CadViewHeader diagnostics={diagnostics} />
      <div className="grid min-w-0 gap-[var(--s-6)] xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <CadViewerPane params={params} diagnostics={diagnostics} />
        <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
          <CadFilesSection
            projectId={params.projectId}
            revisionId={params.revisionId}
            jobId={params.jobId}
            diagnostics={diagnostics}
          />
          <CadScaleSection scale={diagnostics.scale} />
          <CadChecksSection checks={diagnostics.checks} frame={diagnostics.frame} />
        </div>
      </div>
    </article>
  );
};
