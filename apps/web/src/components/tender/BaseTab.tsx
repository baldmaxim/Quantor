'use client';

import type { TenderBaseReleaseRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import {
  Button,
  ButtonLink,
  EmptyState,
  ErrorState,
  SkeletonRows,
  StatusBadge,
  buttonClassName,
  cx,
} from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { formatBytes, formatWhen } from '@/lib/format';
import { useHasPermission } from '@/lib/session';
import { TENDER_BASE_RELEASE } from '@/lib/tender/access';
import {
  tenderBaseDownloadUrl,
  useRevokeTenderBaseRelease,
  useTenderBaseReleases,
} from '@/lib/tender/queries';

import { BaseReleaseDialog } from './BaseReleaseDialog';
import { RevokeReleaseDialog } from './RevokeReleaseDialog';

/**
 * Раздел «База объекта»: выпуски базы (неизменяемые ZIP для TENDER), «Выпустить базу» для
 * координатора. Скачанный ZIP кладут в `TENDER/Работа/Quantor/Базы/<объект>/` вручную.
 */

interface ITabProps {
  readonly projectId: string;
}

const TH = 'px-[var(--s-4)] py-[var(--s-3)] font-semibold';
const TD =
  'px-[var(--s-4)] py-[var(--s-3)] align-top text-sm max-md:flex max-md:justify-between max-md:gap-[var(--s-4)] max-md:px-0 max-md:py-[var(--s-1)] max-md:before:text-xs max-md:before:text-muted max-md:before:content-[attr(data-label)]';

const ReleaseRow: FC<{
  readonly projectId: string;
  readonly release: TenderBaseReleaseRead;
  readonly canRevoke: boolean;
  readonly onRevoke: () => void;
}> = ({ projectId, release, canRevoke, onRevoke }) => {
  const revoked = release.revoked_at !== null;
  const withDxf = release.views.filter((view) => view.dxf_sha256 !== '').length;
  const dim = revoked ? 'line-through text-muted' : '';

  return (
    <tr className="border-b border-border last:border-b-0 max-md:flex max-md:flex-col max-md:px-[var(--s-5)] max-md:py-[var(--s-4)]">
      <td data-label="Выпуск" className={cx(TD, 'tabular font-semibold', dim)}>
        #{release.number}
      </td>
      <td data-label="Дата" className={cx(TD, 'text-muted')}>
        {formatWhen(release.released_at)}
      </td>
      <td data-label="Кто" className={cx(TD, dim)}>
        {release.released_by_name ?? '—'}
      </td>
      <td data-label="Видов" className={cx(TD, 'tabular')}>
        {release.views.length}
      </td>
      <td data-label="С DXF" className={cx(TD, 'tabular')}>
        {release.include_dxf ? withDxf : '—'}
      </td>
      <td data-label="Размер" className={cx(TD, 'tabular')}>
        {formatBytes(release.size_bytes)}
      </td>
      <td data-label="Комментарий" className={cx(TD, '[overflow-wrap:anywhere]')}>
        {release.comment || '—'}
      </td>
      <td className={cx(TD, 'max-md:justify-start')}>
        <span className="flex flex-wrap items-center gap-[var(--s-3)]">
          {revoked ? (
            <StatusBadge tone="danger">Отозван</StatusBadge>
          ) : (
            <>
              <a
                href={tenderBaseDownloadUrl(projectId, release.id)}
                download
                className={buttonClassName({ compact: true })}
              >
                Скачать
              </a>
              {canRevoke && (
                <Button compact variant="danger" onClick={onRevoke}>
                  Отозвать
                </Button>
              )}
            </>
          )}
        </span>
      </td>
    </tr>
  );
};

export const BaseTab: FC<ITabProps> = ({ projectId }) => {
  const releases = useTenderBaseReleases(projectId, true);
  const canRelease = useHasPermission(TENDER_BASE_RELEASE);
  const revoke = useRevokeTenderBaseRelease(projectId);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<TenderBaseReleaseRead | null>(null);

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <p className="m-0 max-w-[70ch] flex-1 basis-[280px] text-sm text-muted">
          База объекта — кадры листов, оси, зоны, конструкции и размещение этажей. Скачанный ZIP
          положите в <span className="mono">TENDER/Работа/Quantor/Базы/&lt;объект&gt;/</span>.
        </p>
        {canRelease && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            Выпустить базу
          </Button>
        )}
      </div>

      {releases.isPending && <SkeletonRows rows={4} />}
      {releases.isError && (
        <ErrorState
          title="Выпуски базы не загрузились"
          code={extractCode(releases.error)}
          description={extractMessage(releases.error) ?? errorMessage(extractCode(releases.error))}
          onRetry={() => void releases.refetch()}
        />
      )}
      {releases.data && releases.data.length === 0 && (
        <EmptyState
          compact
          title="Выпусков базы пока нет"
          description="База собирается из этажей «Здания»: у этажа должны быть посчитаны конструкции (шаг «CAD по листам»). В окне «Выпустить базу» готовые этажи отмечены сами; выпуск не меняется, его можно только отозвать."
          action={
            <ButtonLink href={`/projects/${projectId}/building3d`}>Открыть «Здание»</ButtonLink>
          }
        />
      )}
      {releases.data && releases.data.length > 0 && (
        <div className="rounded-[var(--radius-md)] border border-border-strong bg-surface">
          <table
            aria-label="Выпуски базы"
            className="w-full border-collapse text-left max-md:block"
          >
            <thead className="max-md:sr-only">
              <tr className="border-b border-border-strong bg-surface-muted text-micro font-semibold tracking-[0.06em] text-muted uppercase">
                <th scope="col" className={TH}>
                  Выпуск
                </th>
                <th scope="col" className={TH}>
                  Дата
                </th>
                <th scope="col" className={TH}>
                  Кто
                </th>
                <th scope="col" className={TH}>
                  Видов
                </th>
                <th scope="col" className={TH}>
                  С DXF
                </th>
                <th scope="col" className={TH}>
                  Размер
                </th>
                <th scope="col" className={TH}>
                  Комментарий
                </th>
                <th scope="col" className={TH}>
                  Действия
                </th>
              </tr>
            </thead>
            <tbody className="max-md:block">
              {releases.data.map((release) => (
                <ReleaseRow
                  key={release.id}
                  projectId={projectId}
                  release={release}
                  canRevoke={canRelease}
                  onRevoke={() => setRevoking(release)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <BaseReleaseDialog projectId={projectId} open={creating} onClose={() => setCreating(false)} />
      <RevokeReleaseDialog
        release={revoking}
        busy={revoke.isPending}
        error={revoke.isError ? revoke.error : null}
        onClose={() => setRevoking(null)}
        onConfirm={(id) => revoke.mutate(id, { onSuccess: () => setRevoking(null) })}
      />
    </div>
  );
};
