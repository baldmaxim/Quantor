import type * as ApiClient from '@quantor/api-client';
import type { ProjectAiPipelineRead, ProjectAiSheetRow } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ read: vi.fn(), run: vi.fn(), codex: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readProjectAiPipeline: mocks.read,
  runProjectAiStage: mocks.run,
  startCadOutlineReview: mocks.codex,
}));

import { ProjectAiStages } from './ProjectAiStages';

const sheet = (overrides: Partial<ProjectAiSheetRow> = {}): ProjectAiSheetRow => ({
  document_name: 'АР.pdf',
  revision_id: 'rev-1',
  page_index: 4,
  sheet_position: 5,
  sheet_title: 'План 1 этажа',
  convert_job_id: 'conv-1',
  view: 0,
  walls_job_id: 'walls-1',
  review_available: true,
  stage1: { state: 'ok' },
  stage2: {
    state: 'ok',
    rounds_done: 1,
    rounds_max: 3,
    exhausted: false,
    last_verdict: 'ready_for_human_review',
    last_findings: 0,
  },
  stage3: { state: 'not_started', codex_available: false },
  stage4: { open_remarks: 2, approved: false },
  ...overrides,
});

const summary = (stage: number, over: Record<string, unknown> = {}) => ({
  stage,
  title: [
    '',
    'Прогон чертежей',
    'Проверка Claude и перестроение',
    'Верификация',
    'Приёмка человеком',
  ][stage] as string,
  total: 4,
  done: 1,
  running: 0,
  failed: 0,
  needs_human: 0,
  status: 'attention',
  ...over,
});

const data = (over: Partial<ProjectAiPipelineRead> = {}): ProjectAiPipelineRead => ({
  server_time: '2026-11-25T10:00:00Z',
  available: true,
  max_iterations: 3,
  codex_available: false,
  active: false,
  stages: [
    summary(1, { done: 4, status: 'done' }),
    summary(2, { running: 1, status: 'running', cost_usd: 0.75, duration_ms: 2000 }),
    summary(3, { failed: 2 }),
    summary(4, { needs_human: 3 }),
  ] as ProjectAiPipelineRead['stages'],
  sheets: [sheet()],
  ...over,
});

const renderStages = () =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ProjectAiStages projectId="p-1" />
    </QueryClientProvider>,
  );

describe('ProjectAiStages', () => {
  beforeEach(() => {
    mocks.read.mockReset();
    mocks.run.mockReset();
    mocks.codex.mockReset();
  });

  it('показывает счётчики, бейджи и расход этапов', async () => {
    mocks.read.mockResolvedValue({ data: data() });
    renderStages();
    const first = await screen.findByTestId('ai-stage-1');
    expect(within(first).getByText('4 из 4 листов')).toBeInTheDocument();
    expect(within(first).getByText('Готово')).toBeInTheDocument();
    const second = screen.getByTestId('ai-stage-2');
    expect(within(second).getByText('Идёт')).toBeInTheDocument();
    expect(within(second).getByText('Расход Claude: $0.75 · 2 с')).toBeInTheDocument();
    expect(within(screen.getByTestId('ai-stage-3')).getByText('Ошибки 2')).toBeInTheDocument();
    expect(within(screen.getByTestId('ai-stage-4')).getByText('Нужен человек')).toBeInTheDocument();
  });

  it('запуск проверки Claude вызывает этап review', async () => {
    mocks.read.mockResolvedValue({ data: data() });
    mocks.run.mockResolvedValue({ data: { queued: 2, skipped: [] } });
    renderStages();
    fireEvent.click(await screen.findByRole('button', { name: 'Запустить проверку Claude' }));
    expect(await screen.findByText('Поставлено: 2, пропущено: 0.')).toBeInTheDocument();
    expect(mocks.run).toHaveBeenCalledWith(
      expect.objectContaining({ path: { project_id: 'p-1', stage: 'review' } }),
    );
  });

  it('Codex недоступен: пункт неактивен, верификация идёт через Claude', async () => {
    mocks.read.mockResolvedValue({ data: data() });
    mocks.run.mockResolvedValue({ data: { queued: 1, skipped: [] } });
    renderStages();
    const select = await screen.findByLabelText('Чем верифицировать');
    expect(within(select).getByRole('option', { name: 'Codex (недоступен)' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Верифицировать' }));
    await screen.findByText('Поставлено: 1, пропущено: 0.');
    expect(mocks.run).toHaveBeenCalledWith(
      expect.objectContaining({ path: { project_id: 'p-1', stage: 'verify' } }),
    );
    expect(mocks.codex).not.toHaveBeenCalled();
  });

  it('Codex доступен: верификация ставит проверку по видам с codex_available', async () => {
    mocks.read.mockResolvedValue({
      data: data({
        available: false,
        codex_available: true,
        sheets: [sheet({ stage3: { state: 'not_started', codex_available: true } })],
      }),
    });
    mocks.codex.mockResolvedValue({ data: { job_id: 'x' } });
    renderStages();
    fireEvent.click(await screen.findByRole('button', { name: 'Верифицировать' }));
    expect(await screen.findByText('Проверка Codex: поставлено 1, отказов 0.')).toBeInTheDocument();
    expect(mocks.codex).toHaveBeenCalledWith(
      expect.objectContaining({ path: { job_id: 'walls-1' } }),
    );
  });

  it('раскрытие этапа показывает листы со ссылкой в рабочую область', async () => {
    mocks.read.mockResolvedValue({ data: data() });
    renderStages();
    const second = await screen.findByTestId('ai-stage-2');
    fireEvent.click(within(second).getByRole('button', { name: /Проверка Claude/ }));
    const link = await screen.findByRole('link', { name: 'Открыть' });
    const href = link.getAttribute('href') ?? '';
    expect(href).toContain('/projects/p-1/workspace?');
    expect(href).toContain('revision=rev-1');
    expect(href).toContain('page=5');
    expect(href).toContain('job=conv-1');
    expect(screen.getByText(/круг 1 из 3/)).toBeInTheDocument();
  });

  it('без пилота кнопки Claude неактивны', async () => {
    mocks.read.mockResolvedValue({ data: data({ available: false }) });
    renderStages();
    expect(await screen.findByRole('button', { name: 'Запустить проверку Claude' })).toBeDisabled();
  });
});
