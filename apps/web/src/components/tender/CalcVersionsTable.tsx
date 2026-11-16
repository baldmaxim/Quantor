'use client';

import type { TenderCalcRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge, cx } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { formatWhen } from '@/lib/format';
import { useTenderCalcVersions } from '@/lib/tender/queries';
import { VERSION_STATUS_LABELS, VERSION_STATUS_TONES } from '@/lib/tender/present';
import { systemLabel } from '@/lib/tender/systems';

import { SystemSwatch } from './SystemSwatch';

/**
 * История версий репозитория — как список коммитов: номер, подпись, сообщение, автор, дата, статус
 * (sha256 пакета — в карточке версии: в списке API его не отдаёт). Отозванная версия зачёркнута. На телефоне строка — блок.
 */

interface ITableProps {
  readonly projectId: string;
  readonly calc: TenderCalcRead;
  readonly onBack: () => void;
  readonly onOpen: (versionId: string) => void;
}

const TH = 'px-[var(--s-4)] py-[var(--s-3)] font-semibold';
const TD = 'px-[var(--s-4)] py-[var(--s-3)] align-top text-sm max-md:px-0 max-md:py-[var(--s-1)]';

export const CalcVersionsTable: FC<ITableProps> = ({ projectId, calc, onBack, onOpen }) => {
  const versions = useTenderCalcVersions(projectId, calc.id);

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <Button onClick={onBack}>← Все расчёты</Button>
        <h2 className="flex items-center gap-[var(--s-3)] text-lg font-semibold">
          <SystemSwatch system={calc.system} />
          {calc.title}
          <span className="text-sm font-normal text-muted">{systemLabel(calc.system)}</span>
        </h2>
      </div>

      {versions.isPending && <SkeletonRows rows={4} />}
      {versions.isError && (
        <ErrorState
          title="История версий не загрузилась"
          code={extractCode(versions.error)}
          description={extractMessage(versions.error) ?? errorMessage(extractCode(versions.error))}
          onRetry={() => void versions.refetch()}
        />
      )}
      {versions.data && versions.data.versions.length === 0 && (
        <EmptyState compact title="Версий нет" />
      )}
      {versions.data && versions.data.versions.length > 0 && (
        <div className="rounded-[var(--radius-md)] border border-border-strong bg-surface">
          <table
            aria-label="История версий"
            className="w-full border-collapse text-left max-md:block"
          >
            <thead className="max-md:sr-only">
              <tr className="border-b border-border-strong bg-surface-muted text-micro font-semibold tracking-[0.06em] text-muted uppercase">
                <th scope="col" className={TH}>
                  №
                </th>
                <th scope="col" className={TH}>
                  Подпись
                </th>
                <th scope="col" className={TH}>
                  Сообщение
                </th>
                <th scope="col" className={TH}>
                  Автор
                </th>
                <th scope="col" className={TH}>
                  Дата
                </th>
                <th scope="col" className={TH}>
                  Статус
                </th>
              </tr>
            </thead>
            <tbody className="max-md:block">
              {versions.data.versions.map((version) => {
                const withdrawn = version.status === 'withdrawn';
                return (
                  <tr
                    key={version.id}
                    className="cursor-pointer border-b border-border last:border-b-0 hover:bg-surface-muted max-md:flex max-md:flex-col max-md:px-[var(--s-5)] max-md:py-[var(--s-4)]"
                    onClick={() => onOpen(version.id)}
                  >
                    <td className={cx(TD, 'tabular', withdrawn && 'line-through text-muted')}>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          onOpen(version.id);
                        }}
                        aria-label={`Открыть версию №${version.number}`}
                        className="press min-h-[44px] min-w-[44px] text-left font-semibold text-accent hover:underline md:min-h-0 md:min-w-0"
                      >
                        №{version.number}
                      </button>
                    </td>
                    <td className={cx(TD, withdrawn && 'line-through text-muted')}>
                      {version.label}
                    </td>
                    <td
                      className={cx(
                        TD,
                        '[overflow-wrap:anywhere]',
                        withdrawn && 'line-through text-muted',
                      )}
                    >
                      {version.message || '—'}
                    </td>
                    <td className={cx(TD, withdrawn && 'line-through text-muted')}>
                      {version.author}
                    </td>
                    <td className={cx(TD, 'text-muted')}>{formatWhen(version.uploaded_at)}</td>
                    <td className={TD}>
                      <StatusBadge tone={VERSION_STATUS_TONES[version.status]}>
                        {VERSION_STATUS_LABELS[version.status]}
                      </StatusBadge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
