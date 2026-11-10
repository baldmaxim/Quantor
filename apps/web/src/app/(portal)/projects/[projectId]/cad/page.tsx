'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, use, useEffect } from 'react';

import { EmptyState, SkeletonRows } from '@/components/ui';
import { cadAccess } from '@/lib/cad/access';
import { parseSelection } from '@/lib/cad/selection';
import { cadRedirectHref } from '@/lib/cad/workspace-url';
import { useFeatures, useMeta, useSheets } from '@/lib/queries';

/**
 * Старый адрес страницы PDF → CAD. Весь интерфейс CAD живёт во вкладке «CAD» рабочей области
 * (флаг `cad.export`, ADR-0036), поэтому маршрут только переводит адрес:
 * `?revision&job&page=<индекс>&view` -> `/workspace?revision&page=<позиция листа>&tab=cad&job&view`.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const SHELL = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';

const Redirect = ({ projectId }: { projectId: string }) => {
  const router = useRouter();
  const selection = parseSelection(useSearchParams());
  // Позиция листа в рабочей области - не индекс страницы PDF: нужен список листов ревизии.
  const needSheets = selection.revision !== null && selection.page !== null;
  const sheets = useSheets(needSheets ? selection.revision : null);
  const waiting = needSheets && sheets.isPending;
  // Строка адреса: эффект зависит от неё, а не от объекта выбора, который новый на каждый рендер.
  const href = waiting ? null : cadRedirectHref(projectId, selection, sheets.data?.items ?? null);

  useEffect(() => {
    if (href !== null) router.replace(href, { scroll: false });
  }, [href, router]);

  return <SkeletonRows rows={6} />;
};

const CadPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const meta = useMeta();
  const access = cadAccess(meta.isSuccess, useFeatures());

  if (access === 'hidden') {
    return (
      <main className={SHELL}>
        <EmptyState title="Страница не найдена" />
      </main>
    );
  }

  return (
    <main className={SHELL}>
      {access === 'pending' ? (
        <SkeletonRows rows={6} />
      ) : (
        // useSearchParams требует границы приостановки (иначе маршрут не предрендерить).
        <Suspense fallback={<SkeletonRows rows={6} />}>
          <Redirect projectId={projectId} />
        </Suspense>
      )}
    </main>
  );
};

export default CadPage;
