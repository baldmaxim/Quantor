'use client';

import type { DocumentRead, DocumentRevisionRead } from '@quantor/api-client';
import type { FC } from 'react';

import { ButtonLink, Skeleton, StatusBadge } from '@/components/ui';
import { IconBim, IconPdf, IconZip } from '@/components/ui/icons';
import { errorMessage } from '@/lib/errors';
import { countOf, documentKind, formatBytes, geometryStatus, revisionStatus } from '@/lib/format';
import { SHEETS_FORMS } from '@/lib/format';
import { documentOpenState, isViewable, latestOpenableRevision } from '@/lib/openability';

/**
 * Строка документа в карточке проекта.
 *
 * Показывает два независимых состояния: подготовку листов, от которой зависит просмотр, и
 * распознавание, от которого он не зависит. Действие «Открыть» стоит у каждого готового
 * документа — верхняя кнопка страницы одна, а документов в проекте бывает несколько.
 */

const ICONS: Record<string, typeof IconPdf> = {
  pdf: IconPdf,
  recognized_package: IconZip,
  revit: IconBim,
  navisworks: IconBim,
  ifc: IconBim,
};

export interface IDocumentRowProps {
  readonly projectId: string;
  readonly document: DocumentRead;
  /** `null`, пока ревизии не загружены. */
  readonly revisions: readonly DocumentRevisionRead[] | null;
  readonly total: number;
}

export const DocumentRow: FC<IDocumentRowProps> = ({ projectId, document, revisions, total }) => {
  const Icon = ICONS[document.document_kind] ?? IconPdf;
  const latest = revisions?.at(-1) ?? null;
  const openable = revisions ? latestOpenableRevision(document, revisions) : null;
  const state = revisions ? documentOpenState(document, revisions) : null;

  const recognition = latest ? revisionStatus(latest.processing_status) : null;
  const geometry = latest && isViewable(document) ? geometryStatus(latest.geometry_status) : null;
  const pageCount = latest?.source_metadata?.['page_count'];
  const sheets = latest && latest.sheet_count > 0 ? latest.sheet_count : pageCount;

  return (
    <div className="grid grid-cols-[22px_1fr_auto] items-center gap-[var(--s-5)] border-b border-border py-[var(--s-4)] last:border-b-0">
      <Icon className="text-muted" />

      <div className="min-w-0">
        <p className="truncate text-sm">{document.display_name}</p>
        <p className="mono text-xs text-muted">
          {documentKind(document.document_kind)}
          {latest && ` · ${formatBytes(latest.source_size)}`}
          {typeof sheets === 'number' && ` · ${countOf(sheets, SHEETS_FORMS)}`}
          {total > 1 && ` · ревизий: ${total}`}
        </p>

        {latest?.processing_error_code && (
          <p className="mt-[var(--s-2)] text-xs text-danger">
            {errorMessage(latest.processing_error_code)}
          </p>
        )}

        {state?.kind === 'geometry_failed' && (
          <p className="mt-[var(--s-2)] text-xs text-danger">
            Листы подготовить не удалось
            {state.errorCode ? `: ${errorMessage(state.errorCode)}` : '.'}
          </p>
        )}
      </div>

      <div className="flex items-center gap-[var(--s-4)]">
        {geometry && <StatusBadge tone={geometry.tone}>{geometry.label}</StatusBadge>}

        {recognition ? (
          <StatusBadge tone={recognition.tone}>{recognition.label}</StatusBadge>
        ) : (
          <Skeleton className="h-[16px] w-[90px]" />
        )}

        {openable && (
          <ButtonLink
            href={`/projects/${projectId}/workspace?revision=${openable.id}`}
            aria-label={`Открыть ${document.display_name}`}
            className="flex-none"
          >
            Открыть
          </ButtonLink>
        )}
      </div>
    </div>
  );
};
