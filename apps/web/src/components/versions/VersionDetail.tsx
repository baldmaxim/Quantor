'use client';

import type { DocumentRead, DocumentRevisionRead, TenderVersionRead } from '@quantor/api-client';
import { useState } from 'react';

import { CompositionTable } from '@/components/versions/CompositionTable';
import { DeleteDraftDialog } from '@/components/versions/DeleteDraftDialog';
import { FreezeDialog } from '@/components/versions/FreezeDialog';
import { HubLinkPanel } from '@/components/versions/HubLinkPanel';
import { Button, StatusBadge } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { errorMessage, extractCode } from '@/lib/errors';
import { formatWhen } from '@/lib/format';
import { useUpdateTenderVersion, versionTitle } from '@/lib/tender-versions';

/**
 * Карточка версии: подпись, связь с HUBTender, состав, заморозка и удаление черновика.
 * У замороженной версии всё только для чтения; отпечаток показан полностью.
 */

interface IVersionDetailProps {
  projectId: string;
  version: TenderVersionRead;
  projectLinked: boolean;
  projectDocuments: readonly DocumentRead[];
  revisionsOf: (documentId: string) => readonly DocumentRevisionRead[] | null;
  onDeleted: () => void;
}

export const VersionDetail = ({
  projectId,
  version,
  projectLinked,
  projectDocuments,
  revisionsOf,
  onDeleted,
}: IVersionDetailProps) => {
  const editable = version.status === 'draft';
  const [freezing, setFreezing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [label, setLabel] = useState(version.label ?? '');
  const update = useUpdateTenderVersion(projectId, version.id);

  const labelChanged = label.trim() !== (version.label ?? '');

  return (
    <section className="flex min-w-0 flex-col gap-[var(--s-6)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-5)] py-[var(--s-5)] md:px-[var(--s-6)]">
      <header className="flex flex-wrap items-center gap-[var(--s-3)]">
        <h2 className="text-base font-medium wrap-anywhere">{versionTitle(version)}</h2>
        <StatusBadge tone={editable ? 'warning' : 'success'}>
          {editable ? 'черновик' : 'заморожена'}
        </StatusBadge>
        {editable && (
          <span className="ml-auto flex flex-wrap items-center gap-[var(--s-3)]">
            <Button variant="danger" onClick={() => setDeleting(true)}>
              Удалить черновик
            </Button>
            <Button
              variant="primary"
              disabled={version.documents.length === 0}
              title={version.documents.length === 0 ? 'В составе нет документов' : undefined}
              onClick={() => setFreezing(true)}
            >
              Заморозить
            </Button>
          </span>
        )}
      </header>

      {editable ? (
        <form
          className="flex flex-wrap items-end gap-[var(--s-4)]"
          onSubmit={(event) => {
            event.preventDefault();
            update.mutate({ label: label.trim() || null });
          }}
        >
          <label className="flex min-w-0 flex-1 basis-[240px] flex-col gap-[var(--s-1)] text-xs text-muted">
            Подпись
            <ClearableInput
              label="Подпись версии"
              value={label}
              maxLength={200}
              wrapperClassName="w-full"
              onChange={(event) => setLabel(event.target.value)}
              onClear={() => setLabel('')}
            />
          </label>
          <Button
            type="submit"
            disabled={!labelChanged}
            loading={update.isPending}
            loadingLabel="Сохраняем…"
          >
            Сохранить подпись
          </Button>
          {update.error && (
            <p role="alert" className="basis-full text-sm text-danger">
              {errorMessage(extractCode(update.error))}
            </p>
          )}
        </form>
      ) : (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-[var(--s-6)] gap-y-[var(--s-2)] text-sm">
          <dt className="text-muted">Номер тендера</dt>
          <dd className="m-0 wrap-anywhere">{version.tender_number ?? 'не задан'}</dd>
          {version.frozen_at && (
            <>
              <dt className="text-muted">Заморожена</dt>
              <dd className="m-0">{formatWhen(version.frozen_at)}</dd>
            </>
          )}
          <dt className="text-muted">Отпечаток</dt>
          <dd className="mono m-0 text-xs break-all">{version.manifest_sha256}</dd>
        </dl>
      )}

      <HubLinkPanel projectId={projectId} version={version} projectLinked={projectLinked} />

      <section className="flex flex-col gap-[var(--s-3)]">
        <h3 className="text-sm font-medium">Состав</h3>
        <CompositionTable
          projectId={projectId}
          version={version}
          projectDocuments={projectDocuments}
          revisionsOf={revisionsOf}
        />
      </section>

      <FreezeDialog
        open={freezing}
        onClose={() => setFreezing(false)}
        projectId={projectId}
        version={version}
      />
      <DeleteDraftDialog
        open={deleting}
        onClose={() => setDeleting(false)}
        onDeleted={onDeleted}
        projectId={projectId}
        version={version}
      />
    </section>
  );
};
