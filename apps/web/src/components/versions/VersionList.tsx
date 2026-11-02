'use client';

import type { TenderVersionSummaryRead } from '@quantor/api-client';

import { Button, EmptyState, StatusBadge, cx } from '@/components/ui';
import { DOCUMENTS_FORMS, formatWhen, plural } from '@/lib/format';
import { hashStart, versionTitle } from '@/lib/tender-versions';

/**
 * Список версий проекта: от новой к старой. Выбранная версия подсвечена и открыта справа
 * (на телефоне — под списком).
 */

interface IVersionListProps {
  versions: readonly TenderVersionSummaryRead[];
  selectedId: string | null;
  hasDraft: boolean;
  onSelect: (versionId: string) => void;
  onCreate: () => void;
}

export const VersionList = ({
  versions,
  selectedId,
  hasDraft,
  onSelect,
  onCreate,
}: IVersionListProps) => (
  <section className="flex min-w-0 flex-col gap-[var(--s-4)]">
    <header className="flex flex-wrap items-center justify-between gap-[var(--s-3)]">
      <h2 className="text-sm font-medium">Версии</h2>
      <Button variant="primary" disabled={hasDraft} onClick={onCreate}>
        Создать черновик
      </Button>
      {hasDraft && (
        <p className="basis-full text-xs text-muted">
          Новая версия — после заморозки или удаления черновика.
        </p>
      )}
    </header>

    {versions.length === 0 ? (
      <EmptyState
        compact
        title="Версий пока нет"
        description="Версия — замороженный комплект ревизий документов проекта. Создайте черновик, поправьте состав и заморозьте."
      />
    ) : (
      <ul className="list-none overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
        {versions.map((version) => {
          const selected = version.id === selectedId;
          const frozen = version.status === 'frozen';
          return (
            <li key={version.id} className="border-b border-border last:border-b-0">
              <button
                type="button"
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(version.id)}
                className={cx(
                  'flex min-h-[44px] w-full flex-col gap-[var(--s-2)] px-[var(--s-5)] py-[var(--s-4)] text-left transition-colors duration-[var(--dur-fast)]',
                  selected ? 'bg-accent-soft' : 'hover:bg-surface-muted',
                )}
              >
                <span className="flex flex-wrap items-center gap-[var(--s-3)]">
                  <span className="text-sm font-medium wrap-anywhere">{versionTitle(version)}</span>
                  <StatusBadge tone={frozen ? 'success' : 'warning'}>
                    {frozen ? 'заморожена' : 'черновик'}
                  </StatusBadge>
                </span>
                <span className="text-xs text-muted">
                  {version.document_count} {plural(version.document_count, DOCUMENTS_FORMS)}
                  {version.external_version !== null &&
                    ` · HUBTender, версия ${version.external_version}`}
                </span>
                <span className="text-xs text-muted">
                  {frozen && version.frozen_at
                    ? `заморожена ${formatWhen(version.frozen_at)} · `
                    : `создана ${formatWhen(version.created_at)}`}
                  {frozen && (
                    <span className="mono" title={version.manifest_sha256 ?? undefined}>
                      {hashStart(version.manifest_sha256)}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    )}
  </section>
);
