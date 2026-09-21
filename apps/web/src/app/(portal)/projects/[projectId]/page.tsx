'use client';

import type { DocumentRevisionRead, ProjectJobSummary } from '@quantor/api-client';
import Link from 'next/link';
import { use, useState, ViewTransition } from 'react';

import { DocumentRow } from '@/components/projects/DocumentRow';
import { UploadFilesDialog } from '@/components/projects/UploadFilesDialog';
import { TopBar } from '@/components/shell/TopBar';
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  ProgressRow,
  Skeleton,
  StatusBadge,
} from '@/components/ui';
import { errorMessage } from '@/lib/errors';
import { formatWhen, projectStatus } from '@/lib/format';
import {
  chooseOpenTarget,
  documentOpenState,
  noTargetReason,
  openTargets,
  type OpenState,
} from '@/lib/openability';
import { useDocumentsRevisions, useProject, useProjectDocuments } from '@/lib/queries';

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

  const project = useProject(projectId);
  const documents = useProjectDocuments(projectId);

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

  return (
    <>
      <TopBar
        crumbs={[{ label: 'Проекты', href: '/projects' }, { label: project.data?.name ?? '…' }]}
        status={status ? <StatusBadge tone={status.tone}>{status.label}</StatusBadge> : null}
        actions={
          <>
            <Button onClick={() => setUploading(true)}>Загрузить файл</Button>
            {target ? (
              <Link
                href={workspaceHref(projectId, target.revision.id)}
                className="inline-flex h-[var(--h-ctl)] items-center rounded-[var(--radius-sm)] border border-accent bg-accent px-[var(--s-5)] text-sm font-medium text-accent-contrast hover:bg-accent-hover"
              >
                Открыть рабочую область
              </Link>
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
            <h2 className="flex items-center gap-[var(--s-5)] border-b border-border px-[var(--s-6)] py-[var(--s-5)] text-sm font-medium">
              Документы
              {documents.data && (
                <span className="mono text-xs font-normal text-muted">{documents.data.total}</span>
              )}
            </h2>

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

              {items.map((document) => (
                <DocumentRow
                  key={document.id}
                  projectId={projectId}
                  document={document}
                  revisions={revisions.byDocument.get(document.id)?.items ?? null}
                  total={revisions.byDocument.get(document.id)?.total ?? 0}
                />
              ))}
            </div>
          </section>

          <section className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
            <h2 className="border-b border-border px-[var(--s-6)] py-[var(--s-5)] text-sm font-medium">
              Импорт
            </h2>
            <div className="px-[var(--s-6)] py-[var(--s-5)]">
              {project.isPending && <Skeleton className="h-[96px] w-full" />}

              {project.isError && (
                <ErrorState title="Проект недоступен" onRetry={() => void project.refetch()} />
              )}

              {project.data && !project.data.last_job && (
                <p className="text-sm text-muted">
                  Заданий не было. Импорт запускается при загрузке распознанного пакета; обычный PDF
                  готовится к просмотру и без него.
                </p>
              )}

              {project.data?.last_job && <JobCard job={project.data.last_job} />}
            </div>
          </section>
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

const JobCard = ({ job }: { job: ProjectJobSummary }) => {
  const running = job.status === 'queued' || job.status === 'running';

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <dl className="grid grid-cols-[auto_1fr] gap-x-[var(--s-6)] gap-y-[var(--s-2)]">
        <Field label="Задание">{job.job_type}</Field>
        <Field label="Состояние">{job.status}</Field>
        {job.stage && <Field label="Стадия">{job.stage}</Field>}
        {job.error_code && <Field label="Код ошибки">{job.error_code}</Field>}
        {job.finished_at && <Field label="Завершено">{formatWhen(job.finished_at)}</Field>}
      </dl>

      {running && <ProgressRow value={job.progress} label="Импорт пакета" />}

      {job.error_code && <p className="text-sm text-danger">{errorMessage(job.error_code)}</p>}

      {job.status === 'failed' && (
        <p className="text-sm text-muted">
          Пакет остался в хранилище — повторная загрузка запустит импорт заново.
        </p>
      )}
    </div>
  );
};

const ProjectRoute = ({ params }: IPageProps) => (
  <ViewTransition
    enter={{ 'nav-forward': 'nav-forward', 'nav-back': 'nav-back', default: 'none' }}
    exit={{ 'nav-forward': 'nav-forward', 'nav-back': 'nav-back', default: 'none' }}
    default="none"
  >
    <ProjectPage params={params} />
  </ViewTransition>
);

export default ProjectRoute;
