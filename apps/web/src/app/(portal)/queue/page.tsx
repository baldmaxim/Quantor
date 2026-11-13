'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';

import { QueueBoard } from '@/components/queue/QueueBoard';
import { TopBar } from '@/components/shell/TopBar';

/**
 * Очередь заданий по всем проектам. Фильтр по проекту живёт в адресе (`?project=`):
 * на него ведёт ссылка «Вся очередь» из карточки CAD проекта.
 */

const QueuePage = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const projectId = searchParams.get('project');

  return (
    <>
      <TopBar crumbs={[{ label: 'Очередь заданий' }]} />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-6)]">
          <h1 className="m-0 text-lg font-medium">Очередь заданий</h1>
          <QueueBoard
            projectId={projectId}
            onProjectChange={(next) =>
              router.replace(next === null ? '/queue' : `/queue?project=${next}`)
            }
          />
        </div>
      </main>
    </>
  );
};

/** `useSearchParams` требует границы приостановки, иначе маршрут не предрендерить. */
const QueueRoute = () => (
  <Suspense fallback={null}>
    <QueuePage />
  </Suspense>
);

export default QueueRoute;
