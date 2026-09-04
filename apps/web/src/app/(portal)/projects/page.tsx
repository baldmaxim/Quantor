'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';

import { CreateProjectDialog } from '@/components/projects/CreateProjectDialog';
import { ProjectsTable } from '@/components/projects/ProjectsTable';
import { TopBar } from '@/components/shell/TopBar';
import { Button, EmptyState, ErrorState, SearchInput, SkeletonRows, cx } from '@/components/ui';
import { DOCUMENTS_FORMS, PROJECTS_FORMS, countOf } from '@/lib/format';
import { useProjects, type ProjectsParams } from '@/lib/queries';

/**
 * Список проектов — точка входа в портал.
 *
 * Поиск и сортировка живут в состоянии страницы, а не в URL: пока это единственный
 * список, и разделяемая ссылка на отфильтрованный вид никому не нужна. Как только
 * появится второй такой экран, параметры переедут в строку адреса.
 */

const PAGE_SIZE = 50;

const ProjectsPage = () => {
  const router = useRouter();
  // Открытый диалог живёт в адресе: на него можно дать ссылку, и /projects/new ведёт сюда же.
  const searchParams = useSearchParams();
  const creating = searchParams.get('create') === '1';

  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<ProjectsParams['sort']>('recent');

  const params: ProjectsParams = { search, sort, limit: PAGE_SIZE, offset: 0 };
  const { data, isPending, isError, error, refetch } = useProjects(params);

  return (
    <>
      <TopBar
        crumbs={[{ label: 'Проекты' }]}
        actions={
          <>
            <SearchInput
              label="Поиск по названию"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="w-[240px]"
            />
            <SortToggle value={sort} onChange={setSort} />
          </>
        }
      />

      <main className="min-w-0 flex-1 px-[var(--s-7)] py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-6)]">
          <header className="flex items-end gap-[var(--s-6)]">
            <div>
              <h1 className="text-xl font-semibold tracking-[-0.02em]">Проекты</h1>
              <p className="mt-[var(--s-1)] text-sm text-muted">
                {isPending ? ' ' : summaryLine(data?.total ?? 0, documentTotal(data?.items))}
              </p>
            </div>
            <div className="ml-auto">
              <Button variant="primary" onClick={() => router.push('/projects?create=1')}>
                + Создать проект
              </Button>
            </div>
          </header>

          {isPending && (
            <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
              <SkeletonRows rows={6} />
            </div>
          )}

          {isError && (
            <ErrorState
              title="Не удалось загрузить проекты"
              description={
                error instanceof Error
                  ? 'Проверьте, что бэкенд запущен и доступен по адресу из настроек.'
                  : undefined
              }
              onRetry={() => void refetch()}
            />
          )}

          {!isPending && !isError && data && data.items.length === 0 && (
            <EmptyState
              title={search ? 'Ничего не найдено' : 'Проектов пока нет'}
              description={
                search
                  ? 'Попробуйте изменить запрос — поиск идёт по названию проекта.'
                  : 'Создайте проект и загрузите распознанный пакет или PDF проектной документации.'
              }
              action={
                search ? undefined : (
                  <Button variant="primary" onClick={() => router.push('/projects?create=1')}>
                    Создать проект
                  </Button>
                )
              }
            />
          )}

          {!isPending && !isError && data && data.items.length > 0 && (
            <ProjectsTable projects={data.items} />
          )}
        </div>
      </main>

      <CreateProjectDialog open={creating} onClose={() => router.push('/projects')} />
    </>
  );
};

const summaryLine = (projects: number, documents: number): string =>
  projects === 0
    ? 'Подсчёт строительных объёмов по проектной документации'
    : `${countOf(projects, PROJECTS_FORMS)} · ${countOf(documents, DOCUMENTS_FORMS)}`;

const documentTotal = (items: readonly { document_count: number }[] | undefined): number =>
  (items ?? []).reduce((sum, item) => sum + item.document_count, 0);

interface ISortToggleProps {
  value: ProjectsParams['sort'];
  onChange: (value: ProjectsParams['sort']) => void;
}

const SortToggle = ({ value, onChange }: ISortToggleProps) => (
  <div
    role="group"
    aria-label="Сортировка"
    className="flex h-[var(--h-ctl)] items-center overflow-hidden rounded-[var(--radius-sm)] border border-border-control"
  >
    {(
      [
        ['recent', 'По изменению'],
        ['name', 'По названию'],
      ] as const
    ).map(([key, label]) => (
      <button
        key={key}
        type="button"
        onClick={() => onChange(key)}
        aria-pressed={value === key}
        className={cx(
          'h-full px-[var(--s-5)] text-sm transition-colors',
          value === key ? 'bg-accent-soft text-accent' : 'text-muted hover:bg-surface-muted',
        )}
      >
        {label}
      </button>
    ))}
  </div>
);

/**
 * useSearchParams требует границы приостановки: без неё маршрут не может быть
 * предрендерен статически.
 */
const ProjectsRoute = () => (
  <Suspense fallback={null}>
    <ProjectsPage />
  </Suspense>
);

export default ProjectsRoute;
