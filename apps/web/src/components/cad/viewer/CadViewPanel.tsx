'use client';

import type { CadJobRead } from '@quantor/api-client';
import { useMemo, useState, type FC, type ReactNode } from 'react';

import { EmptyState, ErrorState, Skeleton } from '@/components/ui';
import { cadViewErrorText, useCadView, type ICadViewParams } from '@/lib/cad/view-queries';

import { CadChecksSection } from './CadChecksSection';
import { CadFilesSection } from './CadFilesSection';
import { CadScaleSection } from './CadScaleSection';
import type { ICadSideTab } from './CadSidePanel';
import { CadViewHeader } from './CadViewHeader';
import { CadViewTitle } from './CadViewTitle';
import { CadViewerPane } from './CadViewerPane';

interface ICadViewPanelProps {
  projectId: string;
  revisionId: string;
  job: CadJobRead;
  pageIndex: number;
  view: number;
  /** Ход задания, попытки, действия и итог: раздел «Задание» боковой панели. */
  jobContent: ReactNode;
}

/** Пока вида нет (грузится, отказ, нет результата), экран - прокручиваемое задание и состояние. */
const FallbackShell: FC<{ jobContent: ReactNode; children: ReactNode }> = ({
  jobContent,
  children,
}) => (
  <div className="flex min-w-0 flex-col gap-[var(--s-6)] lg:h-full lg:min-h-0 lg:overflow-auto lg:overscroll-contain">
    {jobContent}
    {children}
  </div>
);

/**
 * Панель вида результата CAD: PDF с наложением CAD на всю свободную площадь и боковая панель
 * (слои, замечания, масштаб, файлы, задание).
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
  jobContent,
}) => {
  const attempt = job.result_attempt;
  // Раздел боковой панели живёт здесь: при смене вида тело панели пересоздаётся, а выбор остаётся.
  const [sideTab, setSideTab] = useState('layers');
  const params = useMemo<ICadViewParams | null>(
    () =>
      attempt === null
        ? null
        : { projectId, revisionId, jobId: job.job_id, attempt, pageIndex, view },
    [projectId, revisionId, job.job_id, attempt, pageIndex, view],
  );

  if (params === null) {
    return (
      <FallbackShell jobContent={jobContent}>
        <EmptyState compact title="Результат попытки ещё не готов" />
      </FallbackShell>
    );
  }

  return (
    <CadViewBody
      key={paramsKey(params)}
      params={params}
      jobContent={jobContent}
      sideTab={sideTab}
      onSideTabChange={setSideTab}
    />
  );
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
interface ICadViewBodyProps {
  params: ICadViewParams;
  jobContent: ReactNode;
  sideTab: string;
  onSideTabChange: (id: string) => void;
}

const CadViewBody: FC<ICadViewBodyProps> = ({ params, jobContent, sideTab, onSideTabChange }) => {
  const query = useCadView(params);

  if (query.isPending) {
    return (
      <FallbackShell jobContent={jobContent}>
        <div className="flex flex-col gap-[var(--s-4)]" role="status" aria-label="Загрузка вида">
          <Skeleton className="h-[20px] w-[60%]" />
          <Skeleton className="h-[16px] w-[80%]" />
          <Skeleton className="h-[240px] w-full" />
        </div>
      </FallbackShell>
    );
  }

  if (query.isError) {
    const { code, text } = cadViewErrorText(query.error);
    return (
      <FallbackShell jobContent={jobContent}>
        <ErrorState
          title="Диагностика вида не загружена"
          code={code}
          description={text}
          onRetry={() => void query.refetch()}
        />
      </FallbackShell>
    );
  }

  const diagnostics = query.data;

  const extraTabs: readonly ICadSideTab[] = [
    {
      id: 'scale',
      label: 'Масштаб',
      content: (
        <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
          <CadScaleSection scale={diagnostics.scale} />
          <CadChecksSection checks={diagnostics.checks} frame={diagnostics.frame} />
        </div>
      ),
    },
    {
      id: 'files',
      label: 'Файлы',
      content: (
        <CadFilesSection
          projectId={params.projectId}
          revisionId={params.revisionId}
          jobId={params.jobId}
          diagnostics={diagnostics}
        />
      ),
    },
    {
      id: 'job',
      label: 'Задание',
      content: (
        <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
          <CadViewHeader diagnostics={diagnostics} />
          {jobContent}
        </div>
      ),
    },
  ];

  return (
    <article className="min-w-0 lg:h-full lg:min-h-0">
      <CadViewerPane
        params={params}
        diagnostics={diagnostics}
        heading={<CadViewTitle diagnostics={diagnostics} />}
        extraTabs={extraTabs}
        sideTab={sideTab}
        onSideTabChange={onSideTabChange}
      />
    </article>
  );
};
