'use client';

import type { DocumentRead, DocumentRevisionRead, ProjectJobSummary } from '@quantor/api-client';
import type { FC, ReactNode } from 'react';

import { Button, ButtonLink, Skeleton, StatusBadge } from '@/components/ui';
import { errorMessage } from '@/lib/errors';
import { geometryStatus, revisionStatus } from '@/lib/format';
import {
  documentOpenState,
  isViewable,
  latestOpenableRevision,
  noTargetReason,
} from '@/lib/openability';

import { DocumentCadPipeline } from './DocumentCadPipeline';
import { ImportJobCard } from './ImportJobCard';

/**
 * Панель «Обработка» выбранного документа: подготовка листов и распознавание, конвейер CAD по
 * листам (за флагом `cad.export`, только для PDF) и - как проектный факт - импорт пакета.
 */

export interface IDocumentPipelinePanelProps {
  readonly projectId: string;
  readonly document: DocumentRead;
  /** `null`, пока ревизии не загружены. */
  readonly revisions: readonly DocumentRevisionRead[] | null;
  readonly cadEnabled: boolean;
  /** Последнее задание проекта (импорт пакета); `null`/`undefined` - заданий не было. */
  readonly importJob?: ProjectJobSummary | null;
}

const Section = ({ title, children }: { title: string; children: ReactNode }) => (
  <section className="border-t border-border pt-[var(--s-5)] first:border-t-0 first:pt-0">
    <h3 className="mb-[var(--s-4)] text-micro font-semibold tracking-[0.06em] text-muted uppercase">
      {title}
    </h3>
    {children}
  </section>
);

export const DocumentPipelinePanel: FC<IDocumentPipelinePanelProps> = ({
  projectId,
  document,
  revisions,
  cadEnabled,
  importJob = null,
}) => {
  const latest = revisions?.at(-1) ?? null;
  const openable = revisions ? latestOpenableRevision(document, revisions) : null;
  const state = revisions ? documentOpenState(document, revisions) : null;
  const viewable = isViewable(document);

  const recognition = latest ? revisionStatus(latest.processing_status) : null;
  const geometry = latest && viewable ? geometryStatus(latest.geometry_status) : null;

  return (
    <section
      aria-label="Обработка документа"
      className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface"
    >
      <header className="flex flex-wrap items-center gap-[var(--s-4)] border-b border-border px-[var(--s-6)] py-[var(--s-3)]">
        <div className="min-w-0 flex-1">
          <p className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
            Обработка
          </p>
          <h2 className="text-sm font-medium [overflow-wrap:anywhere]">{document.display_name}</h2>
        </div>
        {openable ? (
          <ButtonLink
            href={`/projects/${projectId}/workspace?revision=${openable.id}`}
            variant="primary"
            aria-label={`Открыть ${document.display_name} в рабочей области`}
            transitionTypes={['nav-forward']}
          >
            Открыть
          </ButtonLink>
        ) : (
          <Button
            variant="primary"
            disabled
            title={state ? noTargetReason([state]) : 'Ревизии документа ещё загружаются'}
          >
            Открыть
          </Button>
        )}
      </header>

      <div className="flex flex-col gap-[var(--s-5)] px-[var(--s-6)] py-[var(--s-5)]">
        <Section title="Подготовка">
          {revisions === null ? (
            <Skeleton className="h-[20px] w-[180px]" />
          ) : (
            <div className="flex flex-col gap-[var(--s-3)]">
              <div className="flex flex-wrap items-center gap-[var(--s-4)]">
                {geometry && <StatusBadge tone={geometry.tone}>{geometry.label}</StatusBadge>}
                {recognition && (
                  <StatusBadge tone={recognition.tone}>{recognition.label}</StatusBadge>
                )}
              </div>
              {latest?.processing_error_code && (
                <p className="text-xs text-danger">{errorMessage(latest.processing_error_code)}</p>
              )}
              {state?.kind === 'geometry_failed' && (
                <p className="text-xs text-danger">
                  Листы подготовить не удалось
                  {state.errorCode ? `: ${errorMessage(state.errorCode)}` : '.'}
                </p>
              )}
            </div>
          )}
        </Section>

        {cadEnabled && viewable && openable && (
          <Section title="CAD">
            <DocumentCadPipeline projectId={projectId} revisionId={openable.id} />
          </Section>
        )}

        {importJob && (
          <Section title="Импорт пакета">
            <ImportJobCard job={importJob} />
          </Section>
        )}
      </div>
    </section>
  );
};
