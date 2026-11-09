'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import type { FC } from 'react';

import { CadJobDetail } from '@/components/cad/CadJobDetail';
import { CadJobList } from '@/components/cad/CadJobList';
import { CadSourcePicker } from '@/components/cad/CadSourcePicker';
import {
  parseSelection,
  selectionQuery,
  withJob,
  withRevision,
  withView,
  type ICadSelection,
} from '@/lib/cad/selection';

interface ICadScreenProps {
  projectId: string;
}

/** Экран PDF → CAD: выбор источника слева, ход и результат выбранного задания справа. */
export const CadScreen: FC<ICadScreenProps> = ({ projectId }) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selection = parseSelection(searchParams);

  // replace, а не push: переключение вида не должно засорять историю браузера.
  const navigate = (next: ICadSelection) => {
    const query = selectionQuery(next);
    router.replace(`/projects/${projectId}/cad${query ? `?${query}` : ''}`, { scroll: false });
  };

  return (
    <div className="mx-auto grid w-full max-w-[1400px] items-start gap-[var(--s-6)] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)]">
      <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
        <CadSourcePicker
          projectId={projectId}
          selectedRevisionId={selection.revision}
          onSelect={(revisionId, jobId) => navigate(withJob(withRevision(revisionId), jobId))}
        />
        {selection.revision && (
          <CadJobList
            // Ключ по ревизии: список другого документа не переиспользуется.
            key={selection.revision}
            projectId={projectId}
            revisionId={selection.revision}
            selectedJobId={selection.job}
            onSelect={(jobId) => navigate(withJob(selection, jobId))}
          />
        )}
      </div>

      <div className="min-w-0">
        {selection.revision && selection.job ? (
          <CadJobDetail
            key={`${selection.revision}:${selection.job}`}
            projectId={projectId}
            revisionId={selection.revision}
            jobId={selection.job}
            selectedPage={selection.page}
            selectedView={selection.view}
            onSelectView={(page, view) => navigate(withView(selection, page, view))}
            onJobCreated={(jobId) => navigate(withJob(selection, jobId))}
          />
        ) : (
          <p className="rounded-[var(--radius-md)] border border-dashed border-border-strong px-[var(--s-6)] py-[var(--s-7)] text-center text-sm text-muted">
            Загрузите PDF или выберите документ проекта — преобразование запустится автоматически.
          </p>
        )}
      </div>
    </div>
  );
};
