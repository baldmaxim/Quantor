'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState, ViewTransition } from 'react';

import { CreateProjectDialog } from '@/components/projects/CreateProjectDialog';
import { TenderHubDialog } from '@/components/projects/TenderHubDialog';
import { ProjectsTable } from '@/components/projects/ProjectsTable';
import { TopBar } from '@/components/shell/TopBar';
import { Button, EmptyState, ErrorState, SearchInput, SkeletonRows, cx } from '@/components/ui';
import { DOCUMENTS_FORMS, PROJECTS_FORMS, countOf } from '@/lib/format';
import { useFeatures, useProjects, type ProjectsParams } from '@/lib/queries';

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
  // Источник тоже в адресе: на окно выбора тендера можно дать ссылку.
  const picking = searchParams.get('tenderhub') === '1';

  const features = useFeatures();

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
              onClear={() => setSearch('')}
              className="min-w-0 flex-1 md:w-[240px] md:flex-none"
            />
            <SortToggle value={sort} onChange={setSort} />
          </>
        }
      />

      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-6)]">
          {/* Заголовок и счётчик живут в шапке — здесь остаётся только действие.
              На телефоне кнопка во всю ширину: это главное действие экрана, и
              промахнуться по нему не должно быть можно. Счётчик дублируется тут же,
              потому что в узкую шапку он не помещается. */}
          <header className="flex flex-col gap-[var(--s-4)] sm:flex-row sm:items-center">
            <p className="text-sm text-muted sm:hidden">
              {isPending ? ' ' : summaryLine(data?.total ?? 0, documentTotal(data?.items))}
            </p>
            <div className="flex flex-col gap-[var(--s-4)] sm:ml-auto sm:flex-row">
              {/* Кнопка появляется, только когда на сервере есть ключ: предлагать
                  источник, из которого ничего не прочитать, — пустое обещание. */}
              {features['integrations.tenderhub'] === true && (
                <Button
                  className="w-full justify-center sm:w-auto"
                  onClick={() => router.push('/projects?tenderhub=1')}
                >
                  Из TenderHUB
                </Button>
              )}
              <Button
                variant="primary"
                className="w-full justify-center sm:w-auto"
                onClick={() => router.push('/projects?create=1')}
              >
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
      <TenderHubDialog open={picking} onClose={() => router.push('/projects')} />
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
    // Утопленная дорожка с приподнятым выбранным сегментом. Сплошная заливка акцентом
    // читалась как нажатая кнопка действия, хотя это переключатель вида.
    className="flex h-[var(--h-ctl)] flex-none items-center gap-[2px] rounded-[var(--radius-sm)] border border-border-control bg-surface-sunken p-[3px]"
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
          'press h-full rounded-[calc(var(--radius-sm)-2px)] px-[var(--s-5)] text-sm whitespace-nowrap',
          value === key
            ? 'bg-surface-raised font-medium text-accent shadow-[var(--shadow-1)]'
            : 'text-muted hover:text-text',
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
    {/* Направление перехода задают ссылки: вглубь — влево, назад — вправо.
        default: 'none' оставляет без движения переходы без типа — возврат
        кнопкой браузера и обновление данных. */}
    <ViewTransition
      enter={{ 'nav-forward': 'nav-forward', 'nav-back': 'nav-back', default: 'none' }}
      exit={{ 'nav-forward': 'nav-forward', 'nav-back': 'nav-back', default: 'none' }}
      default="none"
    >
      <ProjectsPage />
    </ViewTransition>
  </Suspense>
);

export default ProjectsRoute;
