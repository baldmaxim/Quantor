'use client';

import type { ProjectSummary } from '@quantor/api-client';
import Link from 'next/link';

import { StatusBadge, cx } from '@/components/ui';
import { useListAnimation } from '@/lib/animate';
import { DOCUMENTS_FORMS, SHEETS_FORMS, countOf, formatWhen, projectStatus } from '@/lib/format';

/**
 * Список проектов.
 *
 * На десктопе — плотная таблица: проектов будут десятки, и важнее видеть больше строк,
 * чем крупные обложки; у проекта документации всё равно нет осмысленной картинки.
 *
 * На телефоне пять колонок не помещаются, и таблица либо ужимается в нечитаемое,
 * либо уезжает вбок. Поэтому там та же строка разворачивается в карточку — те же
 * данные, другая раскладка.
 */

const COLUMNS = 'minmax(280px,2.4fr) 120px 110px 170px 150px';

export const ProjectsTable = ({ projects }: { projects: readonly ProjectSummary[] }) => {
  // Перестроение при поиске и сортировке: CSS не знает, куда уехала строка,
  // потому что она просто исчезла из разметки.
  const list = useListAnimation<HTMLUListElement>();

  return (
    <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface shadow-[var(--shadow-1)]">
      <div
        role="row"
        className="hidden items-center gap-[var(--s-6)] border-b border-border bg-surface-muted px-[var(--s-6)] py-[var(--s-4)] text-micro tracking-[0.06em] text-muted uppercase md:grid"
        style={{ gridTemplateColumns: COLUMNS }}
      >
        <span>Проект</span>
        <span>Документы</span>
        <span>Листы</span>
        <span>Состояние</span>
        <span>Изменён</span>
      </div>

      <ul ref={list} className="list-none">
        {projects.map((project) => (
          <ProjectRow key={project.id} project={project} />
        ))}
      </ul>
    </div>
  );
};

const ProjectRow = ({ project }: { project: ProjectSummary }) => {
  const status = projectStatus(project.last_job);
  const documents = countOf(project.document_count, DOCUMENTS_FORMS);
  const sheets = project.sheet_count > 0 ? countOf(project.sheet_count, SHEETS_FORMS) : '—';

  return (
    <li className="border-b border-border last:border-b-0">
      <Link
        href={`/projects/${project.id}`}
        // Уход вглубь: страница проекта въезжает справа, список уходит влево.
        transitionTypes={['nav-forward']}
        className={cx(
          'group flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-2)] px-[var(--s-5)] py-[var(--s-5)]',
          'transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]',
          'hover:bg-surface-muted active:bg-surface-sunken',
          'md:grid md:min-h-[var(--h-row)] md:gap-x-[var(--s-6)] md:px-[var(--s-6)] md:py-[var(--s-3)]',
        )}
        style={{ gridTemplateColumns: COLUMNS }}
      >
        {/* На телефоне название занимает всю строку и переносит остальное вниз:
            каждое значение живёт в разметке один раз, меняется только раскладка.
            Дублировать ячейки было бы проще, но экранный диктор прочёл бы всё дважды. */}
        <span className="flex min-w-0 basis-full flex-col md:basis-auto">
          <span className="wrap-anywhere text-sm font-medium md:truncate">{project.name}</span>
          {project.status === 'archived' && <span className="text-xs text-muted">в архиве</span>}
        </span>

        <span className="tabular text-xs text-muted md:text-sm">{documents}</span>
        <span className="tabular text-xs text-muted md:text-sm">{sheets}</span>

        <span className={cx('order-last md:order-none', !status && 'hidden md:inline')}>
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
