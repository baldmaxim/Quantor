'use client';

import type { ProjectSummary } from '@quantor/api-client';
import Link from 'next/link';

import { StatusBadge, cx } from '@/components/ui';
import { DOCUMENTS_FORMS, SHEETS_FORMS, countOf, formatWhen, projectStatus } from '@/lib/format';

/**
 * Список проектов таблицей, а не карточками.
 *
 * Проектов будут десятки, и важнее видеть больше строк, чем крупные обложки: у проекта
 * документации всё равно нет осмысленной картинки, а обложка-заглушка занимала бы
 * половину экрана ради ничего.
 */

const COLUMNS = 'minmax(280px,2.4fr) 120px 110px 170px 150px';

export const ProjectsTable = ({ projects }: { projects: readonly ProjectSummary[] }) => (
  <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
    <div
      role="row"
      className="grid items-center gap-[var(--s-6)] border-b border-border bg-surface-muted px-[var(--s-6)] py-[var(--s-4)] text-micro tracking-[0.06em] text-muted uppercase"
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span>Проект</span>
      <span>Документы</span>
      <span>Листы</span>
      <span>Состояние</span>
      <span>Изменён</span>
    </div>

    <ul className="list-none">
      {projects.map((project) => (
        <ProjectRow key={project.id} project={project} />
      ))}
    </ul>
  </div>
);

const ProjectRow = ({ project }: { project: ProjectSummary }) => {
  const status = projectStatus(project.last_job);

  return (
    <li className="border-b border-border last:border-b-0">
      <Link
        href={`/projects/${project.id}`}
        className={cx(
          'grid min-h-[var(--h-row)] items-center gap-[var(--s-6)] px-[var(--s-6)] py-[var(--s-3)]',
          'transition-colors hover:bg-surface-muted',
        )}
        style={{ gridTemplateColumns: COLUMNS }}
      >
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-medium">{project.name}</span>
          {project.status === 'archived' && <span className="text-xs text-muted">в архиве</span>}
        </span>

        <span className="tabular text-sm text-muted">
          {countOf(project.document_count, DOCUMENTS_FORMS)}
        </span>
        <span className="tabular text-sm text-muted">
          {project.sheet_count > 0 ? countOf(project.sheet_count, SHEETS_FORMS) : '—'}
        </span>

        <span>
          {status ? (
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
          ) : (
            <span className="text-xs text-muted">—</span>
          )}
        </span>

        <span className="text-xs text-muted">{formatWhen(project.updated_at)}</span>
      </Link>
    </li>
  );
};
