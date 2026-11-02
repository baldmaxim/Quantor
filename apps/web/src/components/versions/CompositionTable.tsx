'use client';

import type {
  DocumentRead,
  DocumentRevisionRead,
  TenderVersionDocumentRead,
  TenderVersionRead,
} from '@quantor/api-client';
import { useState } from 'react';

import { Button, EmptyState, StatusBadge } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { errorMessage, extractCode } from '@/lib/errors';
import { formatWhen } from '@/lib/format';
import { usePutVersionDocument, useRemoveVersionDocument } from '@/lib/tender-versions';

/**
 * Состав версии: по одной ревизии на документ, раздел комплекта и участие в модели.
 *
 * В черновике строка правится на месте: ревизия, раздел и «в модель» уходят на сервер сразу,
 * без общей кнопки «Сохранить». У замороженной версии всё только для чтения.
 * Строка на узком экране переносится, а не растягивает страницу вбок.
 */

const FIELD =
  'h-[var(--h-ctl)] max-md:h-[44px] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';

export interface IRevisionsOf {
  (documentId: string): readonly DocumentRevisionRead[] | null;
}

interface ICompositionTableProps {
  projectId: string;
  version: TenderVersionRead;
  projectDocuments: readonly DocumentRead[];
  revisionsOf: IRevisionsOf;
}

export const CompositionTable = ({
  projectId,
  version,
  projectDocuments,
  revisionsOf,
}: ICompositionTableProps) => {
  const editable = version.status === 'draft';
  const included = new Set(version.documents.map((row) => row.document_id));
  const missing = projectDocuments.filter(
    (document) => !included.has(document.id) && (revisionsOf(document.id)?.length ?? 0) > 0,
  );

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      {version.documents.length === 0 ? (
        <EmptyState
          compact
          title="В составе нет документов"
          description={
            editable
              ? 'Добавьте документы проекта ниже: замораживать пустой комплект нечем.'
              : undefined
          }
        />
      ) : (
        <ul className="list-none overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
          {version.documents.map((row) => (
            <CompositionRow
              key={row.document_id}
              projectId={projectId}
              versionId={version.id}
              row={row}
              revisions={revisionsOf(row.document_id)}
              editable={editable}
            />
          ))}
        </ul>
      )}

      {editable && missing.length > 0 && (
        <section className="flex flex-col gap-[var(--s-3)]">
          <h3 className="text-sm font-medium">Документы проекта вне состава</h3>
          <ul className="list-none overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface">
            {missing.map((document) => (
              <MissingRow
                key={document.id}
                projectId={projectId}
                versionId={version.id}
                document={document}
                revisions={revisionsOf(document.id) ?? []}
              />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};

const ROW =
  'flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-3)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] last:border-b-0 md:px-[var(--s-6)]';

const revisionOption = (revision: DocumentRevisionRead, index: number): string =>
  `№${index + 1} · ${revision.revision_label ?? revision.source_filename} · ${formatWhen(revision.created_at)}`;

interface IRowProps {
  projectId: string;
  versionId: string;
  row: TenderVersionDocumentRead;
  revisions: readonly DocumentRevisionRead[] | null;
  editable: boolean;
}

const CompositionRow = ({ projectId, versionId, row, revisions, editable }: IRowProps) => {
  const put = usePutVersionDocument(projectId, versionId);
  const remove = useRemoveVersionDocument(projectId, versionId);
  // Раздел печатается без запросов на каждую букву: уходит на сервер, когда поле отпустили.
  const [section, setSection] = useState(row.section ?? '');

  const busy = put.isPending || remove.isPending;
  const failure = put.error ?? remove.error;

  const save = (patch: { revisionId?: string; section?: string; useInModel?: boolean }) =>
    put.mutate({
      documentId: row.document_id,
      body: {
        document_revision_id: patch.revisionId ?? row.document_revision_id,
        section: (patch.section ?? section).trim() || null,
        use_in_model: patch.useInModel ?? row.use_in_model,
      },
    });

  const commitSection = (value: string) => {
    if (value.trim() !== (row.section ?? '')) save({ section: value });
  };

  return (
    <li className={ROW}>
      <span className="flex min-w-0 flex-1 basis-[220px] flex-col gap-[var(--s-1)]">
        <span className="text-sm font-medium wrap-anywhere">{row.document_name}</span>
        <span className="mono text-xs text-muted" title={row.source_sha256}>
          sha256 {row.source_sha256.slice(0, 12)}…
        </span>
      </span>

      {editable ? (
        <>
          <label className="flex max-w-full min-w-0 flex-col gap-[var(--s-1)] text-xs text-muted">
            Ревизия
            <select
              value={row.document_revision_id}
              disabled={busy || revisions === null}
              onChange={(event) => save({ revisionId: event.target.value })}
              className={`${FIELD} w-full text-text`}
            >
              {/* Пока список ревизий не пришёл, выбранная показывается своим номером. */}
              {(revisions ?? []).length === 0 && (
                <option value={row.document_revision_id}>№{row.revision_number}</option>
              )}
              {(revisions ?? []).map((revision, index) => (
                <option key={revision.id} value={revision.id}>
                  {revisionOption(revision, index)}
                </option>
              ))}
            </select>
          </label>

          <span className="flex flex-col gap-[var(--s-1)] text-xs text-muted">
            Раздел
            <ClearableInput
              label="Раздел"
              value={section}
              maxLength={16}
              placeholder="АР, КР…"
              disabled={busy}
              wrapperClassName="w-[132px]"
              onChange={(event) => setSection(event.target.value)}
              onBlur={(event) => commitSection(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') commitSection(event.currentTarget.value);
              }}
              onClear={() => {
                setSection('');
                commitSection('');
              }}
            />
          </span>

          <label className="flex min-h-[44px] items-center gap-[var(--s-3)] text-sm">
            <input
              type="checkbox"
              checked={row.use_in_model}
              disabled={busy}
              onChange={(event) => save({ useInModel: event.target.checked })}
              className="size-5"
            />
            В модель
          </label>

          <Button
            variant="danger"
            compact
            disabled={busy}
            aria-label={`Убрать из состава: ${row.document_name}`}
            onClick={() => remove.mutate(row.document_id)}
          >
            Убрать
          </Button>
        </>
      ) : (
        <span className="flex flex-wrap items-center gap-[var(--s-4)] text-sm">
          <span>ревизия №{row.revision_number}</span>
          {row.section && <StatusBadge dot={false}>{row.section}</StatusBadge>}
          <span className="text-muted">{row.use_in_model ? 'в модель' : 'вне модели'}</span>
        </span>
      )}

      {failure && (
        <p role="alert" className="basis-full text-xs text-danger">
          {errorMessage(extractCode(failure))}
        </p>
      )}
    </li>
  );
};

interface IMissingRowProps {
  projectId: string;
  versionId: string;
  document: DocumentRead;
  revisions: readonly DocumentRevisionRead[];
}

const MissingRow = ({ projectId, versionId, document, revisions }: IMissingRowProps) => {
  const put = usePutVersionDocument(projectId, versionId);
  // Ревизии отсортированы от старой к новой: по умолчанию в состав идёт последняя.
  const latest = revisions[revisions.length - 1];

  return (
    <li className={ROW}>
      <span className="min-w-0 flex-1 basis-[220px] text-sm wrap-anywhere">
        {document.display_name}
      </span>
      <Button
        compact
        disabled={put.isPending || latest === undefined}
        onClick={() =>
          latest &&
          put.mutate({
            documentId: document.id,
            body: { document_revision_id: latest.id, use_in_model: true },
          })
        }
      >
        Добавить
      </Button>
      {put.error && (
        <p role="alert" className="basis-full text-xs text-danger">
          {errorMessage(extractCode(put.error))}
        </p>
      )}
    </li>
  );
};
