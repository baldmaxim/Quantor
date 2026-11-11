'use client';

import type { DocumentRevisionRead } from '@quantor/api-client';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, use, useRef, useState, ViewTransition } from 'react';

import { DocumentPipelinePanel } from '@/components/projects/DocumentPipelinePanel';
import { DocumentSections } from '@/components/projects/DocumentSections';
import { UploadFilesDialog } from '@/components/projects/UploadFilesDialog';
import { TopBar } from '@/components/shell/TopBar';
import {
  Button,
  ButtonLink,
  EmptyState,
  ErrorState,
  Skeleton,
  StatusBadge,
} from '@/components/ui';
import { projectStatus } from '@/lib/format';
import {
  chooseOpenTarget,
  documentOpenState,
  noTargetReason,
  openTargets,
  type OpenState,
} from '@/lib/openability';
import { CAD_FEATURE } from '@/lib/cad/access';
import { CALC_FEATURE } from '@/lib/calc/access';
import { CONSISTENCY_FEATURE } from '@/lib/consistency/access';
import { TENDER_VERSIONS_FEATURE } from '@/lib/tender-versions';
import { useDocumentsRevisions, useFeatures, useProject, useProjectDocuments } from '@/lib/queries';

/**
 * Карточка проекта.
 *
 * Отвечает на три вопроса: что загружено, что с этим происходит и что уже можно открыть.
 * Открываемость считается по каждому документу отдельно (`lib/openability`), а не по
 * первому попавшемуся PDF: проект с двумя чертежами не должен терять готовый из-за
 * порядка выдачи.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const workspaceHref = (projectId: string, revisionId: string): string =>
  `/projects/${projectId}/workspace?revision=${revisionId}`;

const ProjectPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const [uploading, setUploading] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const panelRef = useRef<HTMLDivElement>(null);

  const project = useProject(projectId);
  const documents = useProjectDocuments(projectId);
  const features = useFeatures();

  const items = documents.data?.items ?? [];
  const revisions = useDocumentsRevisions(items.map((document) => document.id));
  const revisionsOf = (documentId: string): readonly DocumentRevisionRead[] =>
    revisions.byDocument.get(documentId)?.items ?? [];

  // Верхняя кнопка ведёт в самый свежий открываемый документ проекта. Выбор не зависит
  // от порядка списка — иначе он менялся бы вместе с сортировкой выдачи.
  const target = chooseOpenTarget(openTargets(items, revisionsOf));
  const states = items
    .map((document) => documentOpenState(document, revisionsOf(document.id)))
    .filter((state): state is OpenState => state !== null);

  const status = projectStatus(project.data?.last_job);

  // Выбранный документ живёт в адресе (`?doc=`); без него или с чужим id - документ верхней
  // кнопки, а за неимением - первый.
  const requested = searchParams.get('doc');
  const selected =
    items.find((document) => document.id === requested) ??
    items.find((document) => document.id === target?.document.id) ??
    items[0] ??
    null;

  const selectDocument = (documentId: string): void => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('doc', documentId);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });

    // Узкий экран: панель под списком, к ней нужно подвести. Широкий - она рядом.
    if (!window.matchMedia('(min-width: 1024px)').matches) {
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      requestAnimationFrame(() =>
        panelRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' }),
      );
    }
  };

  return (
    <>
      <TopBar
        crumbs={[{ label: 'Проекты', href: '/projects' }, { label: project.data?.name ?? '…' }]}
        status={status ? <StatusBadge tone={status.tone}>{status.label}</StatusBadge> : null}
        actions={
          <>
            {features[TENDER_VERSIONS_FEATURE] === true && (
              <ButtonLink
                href={`/projects/${projectId}/versions`}
                transitionTypes={['nav-forward']}
              >
                Версии тендера
              </ButtonLink>
            )}
            {features[CONSISTENCY_FEATURE] === true && (
              <ButtonLink href={`/projects/${projectId}/sheets`} transitionTypes={['nav-forward']}>
                Листы комплекта
              </ButtonLink>
            )}
            {features[CALC_FEATURE] === true && (
              <ButtonLink href={`/projects/${projectId}/calc`} transitionTypes={['nav-forward']}>
                Расчёты
              </ButtonLink>
            )}
            <Button onClick={() => setUploading(true)}>Загрузить файл</Button>
            {target ? (
              <ButtonLink href={workspaceHref(projectId, target.revision.id)} variant="primary">
                Открыть рабочую область
              </ButtonLink>
            ) : (
              <Button variant="primary" disabled title={noTargetReason(states)}>
                Открыть рабочую область
              </Button>
            )}
          </>
        }
      />

      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto grid w-full max-w-[1400px] items-start gap-[var(--s-6)] lg:grid-cols-[1.6fr_1fr]">
          <section className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
            <header className="flex flex-wrap items-center gap-[var(--s-4)] border-b border-border px-[var(--s-6)] py-[var(--s-3)]">
              <h2 className="flex min-h-[var(--h-ctl)] items-center gap-[var(--s-5)] text-sm font-medium max-md:min-h-[44px]">
                Документы
                {documents.data && (
                  <span className="mono text-xs font-normal text-muted">
                    {documents.data.total}
                  </span>
                )}
              </h2>
            </header>

            <div className="px-[var(--s-6)]">
              {documents.isPending && <Skeleton className="my-[var(--s-6)] h-[64px] w-full" />}

              {documents.isError && (
                <div className="py-[var(--s-6)]">
                  <ErrorState
                    title="Не удалось загрузить документы"
                    onRetry={() => void documents.refetch()}
                  />
                </div>
              )}

              {documents.data?.items.length === 0 && (
                <div className="py-[var(--s-6)]">
                  <EmptyState
                    compact
                    title="Документов пока нет"
                    description="Загрузите PDF или распознанный пакет — они появятся здесь."
                    action={<Button onClick={() => setUploading(true)}>Загрузить файл</Button>}
                  />
                </div>
              )}

              {items.length > 0 && (
                <DocumentSections
                  key={projectId}
                  projectId={projectId}
                  documents={items}
                  revisionsOf={(documentId) => revisions.byDocument.get(documentId)}
                  selectedId={selected?.id ?? null}
                  onSelect={selectDocument}
                />
              )}
            </div>
          </section>

          <div ref={panelRef} className="scroll-mt-[var(--s-6)]">
            {selected ? (
              <DocumentPipelinePanel
                key={selected.id}
                projectId={projectId}
                document={selected}
                revisions={revisions.byDocument.get(selected.id)?.items ?? null}
                cadEnabled={features[CAD_FEATURE] === true}
                importJob={project.data?.last_job ?? null}
              />
            ) : (
              <section className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
                <h2 className="border-b border-border px-[var(--s-6)] py-[var(--s-5)] text-sm font-medium">
                  Обработка
                </h2>
                <div className="px-[var(--s-6)] py-[var(--s-5)]">
                  {documents.isPending ? (
                    <Skeleton className="h-[96px] w-full" />
                  ) : (
                    <p className="text-sm text-muted">Выберите документ, чтобы увидеть обработку.</p>
                  )}
                </div>
              </section>
            )}
          </div>
        </div>
      </main>

      <UploadFilesDialog
        projectId={projectId}
        open={uploading}
        onClose={() => setUploading(false)}
      />
    </>
  );
};

// useSearchParams требует границы приостановки: без неё маршрут не предрендерится.
const ProjectRoute = ({ params }: IPageProps) => (
  <Suspense fallback={null}>
    <ViewTransition
      enter={{ 'nav-forward': 'nav-forward', 'nav-back': 'nav-back', default: 'none' }}
      exit={{ 'nav-forward': 'nav-forward', 'nav-back': 'nav-back', default: 'none' }}
      default="none"
    >
      <ProjectPage params={params} />
    </ViewTransition>
  </Suspense>
);

export default ProjectRoute;
