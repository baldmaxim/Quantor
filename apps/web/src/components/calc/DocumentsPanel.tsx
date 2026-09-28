'use client';

import type { CalcCollectableDocumentRead } from '@quantor/api-client';
import { useState } from 'react';

import { InspectionDialog } from '@/components/calc/InspectionDialog';
import { Button, StatusBadge } from '@/components/ui';
import { SOURCE_CLASS_TITLES, STAGE_TITLES } from '@/lib/calc/format';
import { formatWhen } from '@/lib/format';

/**
 * Документы проекта глазами сбора фактов: что распознано, что проверено и когда.
 *
 * Документ без распознанного текста собирать нечем — кнопка закрыта с объяснением, а не
 * спрятана: так видно, почему по нему «не проверено».
 */

interface IDocumentsPanelProps {
  projectId: string;
  documents: readonly CalcCollectableDocumentRead[];
}

const blockedReason = (document: CalcCollectableDocumentRead): string | undefined => {
  if (!document.recognized) return 'Нет распознанного текста — собирать нечем';
  if (!document.latest) return 'Есть более новая ревизия этого документа';
  return undefined;
};

export const DocumentsPanel = ({ projectId, documents }: IDocumentsPanelProps) => {
  const [selected, setSelected] = useState<CalcCollectableDocumentRead | null>(null);

  return (
    <>
      <ul className="list-none overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
        {documents.map((document) => {
          const blocked = blockedReason(document);
          const last = document.last_inspection;
          return (
            <li
              key={document.document_revision_id}
              className="flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-3)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] last:border-b-0 md:px-[var(--s-6)]"
            >
              <span className="flex min-w-0 flex-1 basis-[240px] flex-col gap-[var(--s-1)]">
                <span className="text-sm font-medium wrap-anywhere">{document.title}</span>
                <span className="text-xs text-muted">
                  {document.recognized
                    ? `распознанных текстовых блоков: ${document.regions_count}`
                    : 'без распознанного текста'}
                  {document.stamp_section &&
                    ` · по штампу: ${document.stamp_section}${
                      document.stamp_stage ? `, ${STAGE_TITLES[document.stamp_stage]}` : ''
                    }`}
                  {!document.latest && ' · устаревшая ревизия'}
                </span>
                {last && (
                  <span className="text-xs text-muted">
                    Собрано {formatWhen(last.created_at)}: {SOURCE_CLASS_TITLES[last.source_class]},
                    корпус {last.building}; принято {last.summary.accepted}, отозвано{' '}
                    {last.summary.withdrawn}
                  </span>
                )}
              </span>
              {last && !document.inspection_current && (
                <StatusBadge tone="warning">собрано прежней версией</StatusBadge>
              )}
              {document.recognized && document.latest && !last && (
                <StatusBadge>не проверен</StatusBadge>
              )}
              <Button
                compact
                disabled={blocked !== undefined}
                title={blocked}
                onClick={() => setSelected(document)}
              >
                {last ? 'Собрать заново' : 'Собрать факты'}
              </Button>
            </li>
          );
        })}
      </ul>
      <InspectionDialog
        projectId={projectId}
        document={selected}
        onClose={() => setSelected(null)}
      />
    </>
  );
};
