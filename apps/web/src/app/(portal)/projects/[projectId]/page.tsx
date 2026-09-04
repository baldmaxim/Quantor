'use client';

import type { DocumentRead, ProjectJobSummary } from '@quantor/api-client';
import Link from 'next/link';
import { use } from 'react';

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
import { IconBim, IconPdf, IconZip } from '@/components/ui/icons';
import { documentKind, formatWhen, projectStatus } from '@/lib/format';
import { useProject, useProjectDocuments } from '@/lib/queries';

/**
 * Карточка проекта.
 *
 * Отвечает на три вопроса: что загружено, что с этим происходит и можно ли уже открыть
 * рабочую область. Кнопка открытия неактивна, пока нет пригодной к отрисовке ревизии —
 * обещать открытие того, чего нет, нельзя.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const ProjectPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const project = useProject(projectId);
  const documents = useProjectDocuments(projectId);

  const status = projectStatus(project.data?.last_job);

  return (
    <>
      <TopBar
        crumbs={[{ label: 'Проекты', href: '/projects' }, { label: project.data?.name ?? '…' }]}
        status={status ? <StatusBadge tone={status.tone}>{status.label}</StatusBadge> : null}
        actions={
          <>
            <Button disabled title="Загрузка файлов появится на следующем шаге">
              Загрузить файл
            </Button>
            <Button variant="primary" disabled title="Просмотрщик появится на следующем шаге">
              Открыть рабочую область
            </Button>
          </>
        }
      />

      <main className="min-w-0 flex-1 px-[var(--s-7)] py-[var(--s-7)]">
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
                    description="Загрузите распознанный пакет или PDF — они появятся здесь."
                  />
                </div>
              )}

              {documents.data?.items.map((document) => (
                <DocumentRow key={document.id} document={document} />
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
                  Заданий не было. Импорт запускается при загрузке распознанного пакета.
                </p>
              )}

              {project.data?.last_job && <JobCard job={project.data.last_job} />}
            </div>
          </section>
        </div>
      </main>
    </>
  );
};

const ICONS: Record<string, typeof IconPdf> = {
  pdf: IconPdf,
  recognized_package: IconZip,
  revit: IconBim,
  navisworks: IconBim,
  ifc: IconBim,
};

const DocumentRow = ({ document }: { document: DocumentRead }) => {
  const Icon = ICONS[document.document_kind] ?? IconPdf;

  return (
    <div className="grid grid-cols-[22px_1fr_auto] items-center gap-[var(--s-5)] border-b border-border py-[var(--s-4)] last:border-b-0">
      <Icon className="text-muted" />
      <div className="min-w-0">
        <p className="truncate text-sm">{document.display_name}</p>
        <p className="mono text-xs text-muted">
          {documentKind(document.document_kind)}
          {document.discipline ? ` · ${document.discipline}` : ''} ·{' '}
          {formatWhen(document.created_at)}
        </p>
      </div>
      <Link
        href={`/projects/${document.project_id}`}
        className="text-xs text-muted transition-colors hover:text-text"
        aria-label={`Ревизии документа ${document.display_name}`}
      >
        Ревизии
      </Link>
    </div>
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

      {job.status === 'failed' && (
        <p className="text-sm text-muted">
          Пакет остался в хранилище — повторная загрузка запустит импорт заново.
        </p>
      )}
    </div>
  );
};

export default ProjectPage;
