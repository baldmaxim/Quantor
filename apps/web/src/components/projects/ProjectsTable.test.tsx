import type { ProjectSummary } from '@quantor/api-client';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ProjectsTable } from './ProjectsTable';

/**
 * Список проектов.
 *
 * Главное здесь — честность: показываем только то, что действительно есть в ответе API,
 * и не выдумываем состояние проекту, у которого не было заданий.
 */

const project = (overrides: Partial<ProjectSummary> = {}): ProjectSummary => ({
  id: '11111111-1111-4111-8111-111111111111',
  name: 'ЖК «Северный», корпус 3 — АР',
  status: 'active',
  source: 'manual',
  external_ref: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-04T08:42:00Z',
  document_count: 3,
  sheet_count: 77,
  last_job: null,
  ...overrides,
});

describe('список проектов', () => {
  it('показывает название, счётчики и ведёт в карточку', () => {
    render(<ProjectsTable projects={[project()]} />);

    const row = screen.getByRole('link', { name: /Северный/ });

    expect(row).toHaveAttribute('href', '/projects/11111111-1111-4111-8111-111111111111');
    expect(within(row).getByText('3 документа')).toBeInTheDocument();
    expect(within(row).getByText('77 листов')).toBeInTheDocument();
  });

  it('без листов ставит прочерк, а не ноль', () => {
    render(<ProjectsTable projects={[project({ sheet_count: 0 })]} />);

    const row = screen.getByRole('link', { name: /Северный/ });

    expect(within(row).queryByText(/0 листов/)).not.toBeInTheDocument();
    expect(within(row).getAllByText('—').length).toBeGreaterThan(0);
  });

  it('проект без заданий не получает выдуманного состояния', () => {
    render(<ProjectsTable projects={[project()]} />);

    expect(screen.queryByText('Готов')).not.toBeInTheDocument();
  });

  it('идущий импорт показывается с долей выполнения', () => {
    render(
      <ProjectsTable
        projects={[
          project({
            last_job: {
              id: 'job-1',
              job_type: 'legacy_import',
              status: 'running',
              progress: 0.64,
              stage: 'regions',
              error_code: null,
              finished_at: null,
            },
          }),
        ]}
      />,
    );

    expect(screen.getByText('Импорт 64 %')).toBeInTheDocument();
  });

  it('провалившийся импорт виден прямо в списке', () => {
    render(
      <ProjectsTable
        projects={[
          project({
            last_job: {
              id: 'job-2',
              job_type: 'legacy_import',
              status: 'failed',
              progress: null,
              stage: null,
              error_code: 'ARCHIVE_LIMIT_EXCEEDED',
              finished_at: '2026-09-04T09:00:00Z',
            },
          }),
        ]}
      />,
    );

    expect(screen.getByText('Ошибка импорта')).toBeInTheDocument();
  });

  it('архивный проект помечен', () => {
    render(<ProjectsTable projects={[project({ status: 'archived' })]} />);

    expect(screen.getByText('в архиве')).toBeInTheDocument();
  });

  it('заголовки колонок на месте', () => {
    render(<ProjectsTable projects={[project()]} />);

    for (const title of ['Проект', 'Документы', 'Листы', 'Состояние', 'Изменён']) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });
});
