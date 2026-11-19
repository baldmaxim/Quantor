'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { FC } from 'react';

import { ProjectNextStep } from '@/components/projects/ProjectSteps';
import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SegmentedControl, SkeletonRows, type ISegmentedOption } from '@/components/ui';
import { useFeatures, useMeta, useProject } from '@/lib/queries';
import { useHasPermission } from '@/lib/session';
import { TENDER_CALC_READ, tenderAccess } from '@/lib/tender/access';

import { BaseTab } from './BaseTab';
import { CalcsTab } from './CalcsTab';
import { TokensTab } from './TokensTab';

/**
 * Страница «Расчёты» проекта (ADR-0051): репозитории расчётов TENDER, база объекта, личные токены.
 * Закрыта флагом `tender.exchange`: при выключенном флаге страницы нет, пока мета не пришла —
 * заглушка загрузки. Раздел, репозиторий и версия живут в адресе (`?tab=&calc=&version=`).
 */

type TabId = 'calcs' | 'base' | 'tokens';

const TABS: readonly ISegmentedOption<TabId>[] = [
  { value: 'calcs', label: 'Расчёты' },
  { value: 'base', label: 'База объекта' },
  { value: 'tokens', label: 'Доступ (токены)' },
];

const MAIN = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';

interface IScreenProps {
  readonly projectId: string;
}

const parseTab = (value: string | null): TabId =>
  value === 'base' || value === 'tokens' ? value : 'calcs';

export const TenderCalcsScreen: FC<IScreenProps> = ({ projectId }) => {
  const meta = useMeta();
  const access = tenderAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);
  const canRead = useHasPermission(TENDER_CALC_READ);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

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

  // Без права чтения расчётов остаётся только выпуск токенов.
  const current: TabId = canRead ? parseTab(searchParams.get('tab')) : 'tokens';
  const options = canRead ? TABS : TABS.filter((option) => option.value === 'tokens');

  const navigate = (patch: Readonly<Record<string, string | null>>): void => {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    router.push(query === '' ? pathname : `${pathname}?${query}`, { scroll: false });
  };

  const changeTab = (next: TabId): void => {
    navigate({ tab: next === 'calcs' ? null : next, calc: null, version: null });
  };

  return (
    <>
      <TopBar
        crumbs={[
          { label: 'Проекты', href: '/projects' },
          { label: project.data?.name ?? '…', href: `/projects/${projectId}` },
          { label: 'Расчёты' },
        ]}
        actions={
          current === 'base' ? <ProjectNextStep projectId={projectId} current="base" /> : null
        }
      />
      <main className={`${MAIN} md:py-[var(--s-7)]`}>
        <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-[var(--s-6)]">
          <SegmentedControl
            label="Раздел страницы"
            layout="wrap"
            value={current}
            options={options}
            onChange={changeTab}
          />
          {current === 'calcs' && (
            <CalcsTab
              projectId={projectId}
              calcId={searchParams.get('calc')}
              versionId={searchParams.get('version')}
              onNavigate={navigate}
            />
          )}
          {current === 'base' && <BaseTab projectId={projectId} />}
          {current === 'tokens' && <TokensTab />}
        </div>
      </main>
    </>
  );
};
