import type * as ApiClient from '@quantor/api-client';
import type {
  CadPipelineRead,
  CadPipelineStageRead,
  DocumentRead,
  DocumentRevisionRead,
} from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ pipeline: vi.fn(), sheets: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readCadPipeline: mocks.pipeline,
  listRevisionSheets: mocks.sheets,
}));

import { DocumentPipelinePanel } from './DocumentPipelinePanel';

const document = (overrides: Partial<DocumentRead> = {}): DocumentRead => ({
  id: 'doc-1',
  project_id: 'p-1',
  display_name: 'План 3 этажа.pdf',
  discipline: null,
  document_kind: 'pdf',
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  ...overrides,
});

const revision = (overrides: Partial<DocumentRevisionRead> = {}): DocumentRevisionRead => ({
  id: 'rev-1',
  document_id: 'doc-1',
  revision_label: null,
  source_filename: 'План 3 этажа.pdf',
  source_mime: 'application/pdf',
  source_size: 2_400_000,
  source_sha256: 'a'.repeat(64),
  processing_status: 'unprocessed',
  processing_error_code: null,
  geometry_status: 'ready',
  geometry_error_code: null,
  sheet_count: 4,
  source_metadata: {},
  created_at: '2026-09-01T10:00:00Z',
  ...overrides,
});

const stage = (overrides: Partial<CadPipelineStageRead> = {}): CadPipelineStageRead => ({
  job_id: 'job-9',
  job_type: 'cad_pdf_convert',
  status: 'succeeded',
  progress: 1,
  stage: null,
  result_status: 'completed_requires_review',
  error_code: null,
  created_at: '2026-11-11T10:00:00Z',
  finished_at: '2026-11-11T10:01:00Z',
  ...overrides,
});

const pipelineWith = (sheets: CadPipelineRead['sheets']): CadPipelineRead => ({
  revision_id: 'rev-1',
  server_time: '2026-11-11T10:00:00Z',
  sheets,
});

const renderPanel = (node: ReactNode) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
};

const panel = (props: Partial<Parameters<typeof DocumentPipelinePanel>[0]> = {}) => (
  <DocumentPipelinePanel
    projectId="p-1"
    document={document()}
    revisions={[revision()]}
    cadEnabled
    {...props}
  />
);

describe('панель обработки документа', () => {
  beforeEach(() => {
    mocks.pipeline.mockReset();
    mocks.sheets.mockReset();
    mocks.sheets.mockResolvedValue({
      data: { items: [{ page_index: 0 }, { page_index: 2 }], total: 2 },
    });
  });

  it('название, «Открыть» в рабочую область и подготовка', () => {
    mocks.pipeline.mockResolvedValue({ data: pipelineWith([]) });
    renderPanel(panel({ cadEnabled: false }));

    expect(screen.getByRole('heading', { name: 'План 3 этажа.pdf' })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Открыть План 3 этажа.pdf в рабочей области' }),
    ).toHaveAttribute('href', '/projects/p-1/workspace?revision=rev-1');
    expect(screen.getByText('Листы готовы')).toBeInTheDocument();
    expect(screen.getByText('Не распознан')).toBeInTheDocument();
  });

  it('флаг CAD выключен: блока CAD нет и конвейер не запрашивается', () => {
    renderPanel(panel({ cadEnabled: false }));

    expect(screen.queryByRole('heading', { name: 'CAD' })).not.toBeInTheDocument();
    expect(mocks.pipeline).not.toHaveBeenCalled();
  });

  it('не PDF: блока CAD нет даже при включённом флаге', () => {
    renderPanel(
      panel({
        document: document({ document_kind: 'recognized_package', display_name: 'пакет.zip' }),
      }),
    );

    expect(screen.queryByRole('heading', { name: 'CAD' })).not.toBeInTheDocument();
    expect(mocks.pipeline).not.toHaveBeenCalled();
  });

  it('листы: шаги, итог и ссылка в CAD с позицией листа и заданием', async () => {
    mocks.pipeline.mockResolvedValue({
      data: pipelineWith([
        {
          page_index: 2,
          page_label: '3',
          calibrated: true,
          convert: stage({ status: 'running', progress: 0.4 }),
          views: [],
        },
        { page_index: 5, page_label: null, calibrated: false, convert: null, views: [] },
      ]),
    });
    renderPanel(panel());

    const sheet = (await screen.findByText('Лист 3')).closest('li') as HTMLElement;
    expect(within(sheet).getByText('Идёт: CAD · 40 %')).toBeInTheDocument();
    expect(within(sheet).getByText('1 из 6')).toBeInTheDocument();
    const steps = within(sheet).getByRole('list', { name: 'Шаги конвейера' });
    expect(within(steps).getAllByRole('listitem')).toHaveLength(6);
    expect(within(steps).getByText('Калибровка')).toBeInTheDocument();
    // Не только цветом: слово состояния для чтения с экрана.
    expect(within(steps).getByText(': идёт')).toBeInTheDocument();

    // Страница 2 - вторая в списке листов ревизии, позиция 2.
    await screen.findByText('Лист 6');
    expect(screen.getByRole('link', { name: 'Открыть Лист 3 в CAD' })).toHaveAttribute(
      'href',
      '/projects/p-1/workspace?revision=rev-1&page=2&tab=cad&job=job-9',
    );
    // Нет листа в списке ревизии: позиция = индекс + 1, задания нет.
    expect(screen.getByRole('link', { name: 'Открыть Лист 6 в CAD' })).toHaveAttribute(
      'href',
      '/projects/p-1/workspace?revision=rev-1&page=6&tab=cad',
    );
    expect(screen.getByText('Нужно: откалибровать лист')).toBeInTheDocument();
  });

  it('листов нет: подсказка', async () => {
    mocks.pipeline.mockResolvedValue({ data: pipelineWith([]) });
    renderPanel(panel());

    expect(
      await screen.findByText(
        'Листы ещё не обрабатывались: откройте документ, откалибруйте лист и запустите преобразование в CAD.',
      ),
    ).toBeInTheDocument();
  });

  it('ошибка загрузки: сообщение и повтор', async () => {
    mocks.pipeline.mockRejectedValue(new Error('сеть'));
    renderPanel(panel());

    expect(await screen.findByText('Не удалось получить состояние CAD')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Повторить/ })).toBeInTheDocument();
  });

  it('импорт пакета показан только при наличии задания', () => {
    const { rerender } = renderPanel(panel({ cadEnabled: false }));
    expect(screen.queryByRole('heading', { name: 'Импорт пакета' })).not.toBeInTheDocument();

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        {panel({
          cadEnabled: false,
          importJob: {
            id: 'j1',
            job_type: 'legacy_import',
            status: 'failed',
            stage: null,
            progress: null,
            error_code: null,
            finished_at: null,
          },
        })}
      </QueryClientProvider>,
    );
    expect(screen.getByRole('heading', { name: 'Импорт пакета' })).toBeInTheDocument();
    expect(screen.getByText(/Пакет остался в хранилище/)).toBeInTheDocument();
  });

  it('документ не открывается: «Открыть» недоступна', () => {
    renderPanel(
      panel({ revisions: [revision({ geometry_status: 'pending', sheet_count: 0 })] }),
    );

    expect(screen.queryByRole('link', { name: /Открыть/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Открыть' })).toBeDisabled();
    expect(mocks.pipeline).not.toHaveBeenCalled();
  });

  it('лист с заголовком плана назван этажом, номер листа - второй подписью', async () => {
    mocks.pipeline.mockResolvedValue({
      data: pipelineWith([
        {
          page_index: 2,
          page_label: '82',
          calibrated: true,
          floor_title: { corps: '9', section: '3', floors: ['14'], text: null },
          convert: stage(),
          views: [],
        },
      ]),
    });
    renderPanel(panel());

    const name = await screen.findByText('К9 · С3 · 14 эт.');
    expect(name).toHaveAttribute('title', 'Корпус 9, секция 3, 14 этаж');
    expect(screen.getByText('Лист 82')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть К9 · С3 · 14 эт. в CAD' })).toBeInTheDocument();
  });

  it('лист: метка 3D DXF и ошибка шага показаны отдельно от дорожки', async () => {
    const done = stage();
    const routes = stage({ job_type: 'cad_mep_route' });
    mocks.pipeline.mockResolvedValue({
      data: pipelineWith([
        {
          page_index: 0,
          page_label: '1',
          calibrated: true,
          convert: stage(),
          views: [
            {
              page: 0,
              view: 1,
              has_dxf: true,
              walls: done,
              zones: done,
              zones_count: 2,
              approved: true,
              routes,
              routes_accepted: true,
              floor3d: stage({ job_type: 'cad_floor3d_dxf' }),
            },
          ],
        },
        {
          page_index: 1,
          page_label: '2',
          calibrated: true,
          convert: stage({ status: 'failed', error_code: 'CAD_ENGINE_FAILED', result_status: null }),
          views: [],
        },
      ]),
    });
    renderPanel(panel());

    const ready = (await screen.findByText('Лист 1')).closest('li') as HTMLElement;
    expect(within(ready).getByText('Готово')).toBeInTheDocument();
    expect(within(ready).getByText('6 из 6')).toBeInTheDocument();
    expect(within(ready).getByText('3D DXF готов')).toBeInTheDocument();

    const failed = (await screen.findByText('Лист 2')).closest('li') as HTMLElement;
    expect(within(failed).getByText('Ошибка: CAD')).toBeInTheDocument();
    expect(
      within(failed).getByText('Движок CAD не выдал проверенный результат.'),
    ).toBeInTheDocument();
    expect(within(failed).queryByText(/3D DXF/)).not.toBeInTheDocument();
  });
});
