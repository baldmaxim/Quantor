'use client';

import type { FC } from 'react';

import { Button, EmptyState, ErrorState, SkeletonRows } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { useTenderBaseReleases, useTenderCalcs } from '@/lib/tender/queries';
import { groupCalcs } from '@/lib/tender/present';
import { disciplineLabel } from '@/lib/tender/systems';

import { CalcCard } from './CalcCard';
import { CalcVersionDetail } from './CalcVersionDetail';
import { CalcVersionsTable } from './CalcVersionsTable';

/**
 * Раздел «Расчёты»: репозитории по разделам → история версий → карточка версии. Выбор живёт в адресе
 * (`calc`, `version`), поэтому ссылку можно переслать, а «назад» браузера возвращает на уровень выше.
 */

interface ITabProps {
  readonly projectId: string;
  readonly calcId: string | null;
  readonly versionId: string | null;
  readonly onNavigate: (patch: Readonly<Record<string, string | null>>) => void;
}

export const CalcsTab: FC<ITabProps> = ({ projectId, calcId, versionId, onNavigate }) => {
  const calcs = useTenderCalcs(projectId, true);
  const releases = useTenderBaseReleases(projectId, true);

  if (calcs.isPending) return <SkeletonRows rows={5} />;

  if (calcs.isError) {
    return (
      <ErrorState
        title="Расчёты не загрузились"
        code={extractCode(calcs.error)}
        description={extractMessage(calcs.error) ?? errorMessage(extractCode(calcs.error))}
        onRetry={() => void calcs.refetch()}
      />
    );
  }

  const selected = calcs.data.calcs.find((calc) => calc.id === calcId) ?? null;

  if (selected && versionId) {
    return (
      <CalcVersionDetail
        projectId={projectId}
        calc={selected}
        versionId={versionId}
        onBack={() => onNavigate({ version: null })}
      />
    );
  }

  if (selected) {
    return (
      <CalcVersionsTable
        projectId={projectId}
        calc={selected}
        onBack={() => onNavigate({ calc: null, version: null })}
        onOpen={(id) => onNavigate({ version: id })}
      />
    );
  }

  if (calcs.data.calcs.length === 0) {
    return (
      <EmptyState
        title="Расчётов пока нет"
        description="Расчёт появится после загрузки пакета из TENDER (навык quantor-obmen). Токен для загрузки выпускается в разделе «Доступ (токены)»."
        action={<Button onClick={() => onNavigate({ tab: 'tokens' })}>Выпустить токен</Button>}
      />
    );
  }

  const latestRelease = Math.max(
    0,
    ...(releases.data ?? []).filter((release) => release.revoked_at === null).map((r) => r.number),
  );

  return (
    <div className="flex flex-col gap-[var(--s-7)]">
      {groupCalcs(calcs.data.calcs).map((group) => (
        <section key={group.discipline} className="flex flex-col gap-[var(--s-5)]">
          <h2 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
            {disciplineLabel(group.discipline)}
          </h2>
          <ul className="m-0 grid list-none grid-cols-1 gap-[var(--s-5)] p-0 md:grid-cols-2 xl:grid-cols-3">
            {group.calcs.map((calc) => (
              <li key={calc.id} className="min-w-0">
                <CalcCard
                  calc={calc}
                  latestRelease={latestRelease}
                  onOpen={() => onNavigate({ calc: calc.id, version: null })}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
};
