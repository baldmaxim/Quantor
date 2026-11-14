'use client';

import type { FC } from 'react';

import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui';
import { consistencyAccess } from '@/lib/consistency/access';
import { useBuildingFrame } from '@/lib/consistency/building-frame-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

import { FrameChecksPanel } from './FrameChecksPanel';
import { FrameRebuildPanel } from './FrameRebuildPanel';
import { FrameTree } from './FrameTree';

/**
 * Экран «Каркас здания» (ADR-0043, С2): корпус → секция → уровень из подтверждённых паспортов
 * листов и проверки комплектности. Закрыт флагом `project.consistency`: при выключенном флаге
 * страницы нет, пока мета не пришла — заглушка загрузки.
 */

interface IScreenProps {
  readonly projectId: string;
}

const MAIN = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';

export const FrameScreen: FC<IScreenProps> = ({ projectId }) => {
  const meta = useMeta();
  const access = consistencyAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);
  const frame = useBuildingFrame(projectId, access === 'open');

  if (access === 'pending') {
    return (
      <main className={MAIN}>
        <SkeletonRows rows={6} />
      </main>
    );
  }

  if (access === 'hidden') {
    return (
      <main className={MAIN}>
        <EmptyState title="Страница не найдена" />
      </main>
    );
  }

  return (
    <>
      <TopBar
        crumbs={[
          { label: 'Проекты', href: '/projects' },
          { label: project.data?.name ?? '…', href: `/projects/${projectId}` },
          { label: 'Каркас здания' },
        ]}
      />
      <main className={`${MAIN} md:py-[var(--s-7)]`}>
        <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-[var(--s-5)]">
          <p className="max-w-[80ch] text-sm text-muted">
            Корпуса, секции и уровни собираются из подтверждённых паспортов листов-планов. Кандидат
            идёт в проверки только после подтверждения. Расхождение источников не решается молча:
            оно остаётся замечанием со ссылкой на лист или ответ к документации.
          </p>
          {frame.isPending && <SkeletonRows rows={6} />}
          {frame.isError && (
            <ErrorState
              title="Каркас не загрузился"
              code={extractCode(frame.error)}
              description={extractMessage(frame.error) ?? errorMessage(extractCode(frame.error))}
              onRetry={() => void frame.refetch()}
            />
          )}
          {frame.data && (
            <>
              <FrameRebuildPanel projectId={projectId} frame={frame.data} />
              <FrameChecksPanel checks={frame.data.checks} />
              <FrameTree projectId={projectId} nodes={frame.data.nodes} />
            </>
          )}
        </div>
      </main>
    </>
  );
};
