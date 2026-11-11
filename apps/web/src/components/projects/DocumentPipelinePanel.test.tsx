import type * as ApiClient from '@quantor/api-client';
import type {
  CadPipelineRead,
  CadPipelineSheetRead,
  CadPipelineStageRead,
  DocumentRead,
  DocumentRevisionRead,
} from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  pipeline: vi.fn(),
  sheets: vi.fn(),
  retry: vi.fn(),
  createJob: vi.fn(),
  readJob: vi.fn(),
  events: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readCadPipeline: mocks.pipeline,
  listRevisionSheets: mocks.sheets,
  retryCadJob: mocks.retry,
  createCadJob: mocks.createJob,
  readCadJob: mocks.readJob,
  readCadEvents: mocks.events,
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

/** Лист конвейера: `title`, `is_plan` и `scale_source` заполняются по умолчанию. */
type SheetInput = Omit<CadPipelineSheetRead, 'title' | 'is_plan' | 'scale_source'> &
  Partial<Pick<CadPipelineSheetRead, 'title' | 'is_plan' | 'scale_source'>>;

const pipelineWith = (sheets: SheetInput[]): CadPipelineRead => ({
  revision_id: 'rev-1',
  server_time: '2026-11-11T10:00:00Z',
  sheets: sheets.map((sheet) => ({ title: null, is_plan: true, scale_source: null, ...sheet })),
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
    mocks.retry.mockReset();
    mocks.createJob.mockReset();
    mocks.readJob.mockReset();
    mocks.events.mockReset();
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
    // Нетронутый лист: не «нужно человеку», а «не запущено».
    expect(screen.getByText('Не запущено')).toBeInTheDocument();
    expect(screen.queryByText(/откалибровать лист/)).not.toBeInTheDocument();
  });

  it('листов нет: подсказка', async () => {
    mocks.pipeline.mockResolvedValue({ data: pipelineWith([]) });
    renderPanel(panel());

    expect(
      await screen.findByText(
        'В документе не найдено листов со словом „План“ в названии и листов с работой CAD',
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
  describe('управление листом', () => {
    const failedConvert = stage({
      job_id: 'job-f',
      status: 'failed',
      error_code: 'CAD_ENGINE_FAILED',
      result_status: null,
    });
    const failedSheet = {
      page_index: 1,
      page_label: '2',
      calibrated: true,
      convert: failedConvert,
      views: [],
    };

    it('шапка листа раскрывает и сворачивает шаги', async () => {
      const user = userEvent.setup();
      mocks.pipeline.mockResolvedValue({
        data: pipelineWith([
          { page_index: 0, page_label: '1', calibrated: true, convert: null, views: [] },
        ]),
      });
      renderPanel(panel());

      const sheet = (await screen.findByText('Лист 1')).closest('li') as HTMLElement;
      const toggle = within(sheet).getByRole('button', { expanded: false });
      expect(within(sheet).queryByRole('list', { name: 'Шаги листа' })).not.toBeInTheDocument();

      await user.click(toggle);
      expect(toggle).toHaveAttribute('aria-expanded', 'true');
      expect(within(sheet).getByRole('list', { name: 'Шаги листа' })).toBeInTheDocument();
      // Не начатое преобразование: главная кнопка следующего шага и «Преобразовать в CAD» у шага.
      expect(
        within(sheet).getByRole('button', { name: 'Следующий шаг: CAD' }),
      ).toBeInTheDocument();
      expect(
        within(sheet).getByRole('button', { name: 'Преобразовать в CAD' }),
      ).toBeInTheDocument();
      // «Открыть» не переключает раскрытие.
      await user.click(within(sheet).getByRole('link', { name: 'Открыть Лист 1 в CAD' }));
      expect(toggle).toHaveAttribute('aria-expanded', 'true');

      await user.click(toggle);
      expect(within(sheet).queryByRole('list', { name: 'Шаги листа' })).not.toBeInTheDocument();
    });

    it('не откалиброван: запуск доступен, калибровка - второстепенная ссылка', async () => {
      const user = userEvent.setup();
      mocks.pipeline.mockResolvedValue({
        data: pipelineWith([
          { page_index: 0, page_label: '1', calibrated: false, convert: null, views: [] },
        ]),
      });
      renderPanel(panel());

      const sheet = (await screen.findByText('Лист 1')).closest('li') as HTMLElement;
      await user.click(within(sheet).getByRole('button', { expanded: false }));
      expect(
        within(sheet).getByRole('button', { name: 'Следующий шаг: CAD' }),
      ).toBeInTheDocument();
      expect(within(sheet).queryByRole('link', { name: 'Перейти: Калибровка' })).toBeNull();
      expect(within(sheet).getByRole('link', { name: 'Откалибровать вручную' })).toHaveAttribute(
        'href',
        '/projects/p-1/workspace?revision=rev-1&page=1&tab=cad',
      );
    });

    it('«Преобразовать в CAD» ставит задание с auto_scale', async () => {
      const user = userEvent.setup();
      mocks.pipeline.mockResolvedValue({
        data: pipelineWith([
          { page_index: 0, page_label: '1', calibrated: false, convert: null, views: [] },
        ]),
      });
      mocks.createJob.mockResolvedValue({ data: { job_id: 'job-new' } });
      renderPanel(panel());

      const sheet = (await screen.findByText('Лист 1')).closest('li') as HTMLElement;
      await user.click(within(sheet).getByRole('button', { expanded: false }));
      await user.click(within(sheet).getByRole('button', { name: 'Преобразовать в CAD' }));

      await waitFor(() => expect(mocks.createJob).toHaveBeenCalledTimes(1));
      expect(mocks.createJob.mock.calls[0]?.[0]).toMatchObject({
        body: { pages: [0], finishes: false, schedules: false, auto_scale: true },
      });
    });

    it('масштаб не подтверждён: «Откалибровать вручную» вместо «Повторить»', async () => {
      const user = userEvent.setup();
      mocks.pipeline.mockResolvedValue({
        data: pipelineWith([
          {
            page_index: 0,
            page_label: '1',
            calibrated: false,
            convert: stage({
              job_id: 'job-u',
              status: 'failed',
              result_status: null,
              error_code: 'CAD_AUTO_SCALE_UNCONFIRMED',
            }),
            views: [],
          },
        ]),
      });
      renderPanel(panel());

      const sheet = (await screen.findByText('Лист 1')).closest('li') as HTMLElement;
      await user.click(within(sheet).getByRole('button', { expanded: false }));
      // Главная ссылка сверху и та же ссылка у шага CAD.
      const links = within(sheet).getAllByRole('link', { name: 'Откалибровать вручную' });
      expect(links).toHaveLength(2);
      for (const link of links) {
        expect(link).toHaveAttribute('href', '/projects/p-1/workspace?revision=rev-1&page=1&tab=cad');
      }
      expect(within(sheet).queryByRole('button', { name: 'Повторить' })).toBeNull();
      expect(
        within(sheet).getAllByText(/Масштаб листа не подтверждён/).length,
      ).toBeGreaterThan(0);
    });

    it('упавший шаг: «Повторить» вызывает повтор задания, обновляет конвейер', async () => {
      const user = userEvent.setup();
      mocks.pipeline.mockResolvedValue({ data: pipelineWith([failedSheet]) });
      mocks.retry.mockResolvedValue({ data: { job_id: 'job-f' } });
      renderPanel(panel());

      const sheet = (await screen.findByText('Лист 2')).closest('li') as HTMLElement;
      await user.click(within(sheet).getByRole('button', { expanded: false }));
      expect(within(sheet).getByRole('button', { name: 'Подробнее' })).toBeInTheDocument();

      await user.click(within(sheet).getByRole('button', { name: 'Повторить' }));
      await waitFor(() => expect(mocks.retry).toHaveBeenCalledTimes(1));
      expect(mocks.retry.mock.calls[0]?.[0]).toMatchObject({
        path: { project_id: 'p-1', revision_id: 'rev-1', job_id: 'job-f' },
      });
      // Конвейер перечитан после запуска.
      await waitFor(() => expect(mocks.pipeline.mock.calls.length).toBeGreaterThan(1));
    });

    it('отказ запуска показан под шагом', async () => {
      const user = userEvent.setup();
      mocks.pipeline.mockResolvedValue({ data: pipelineWith([failedSheet]) });
      mocks.retry.mockRejectedValue({ detail: { code: 'JOB_NOT_RETRYABLE' } });
      renderPanel(panel());

      const sheet = (await screen.findByText('Лист 2')).closest('li') as HTMLElement;
      await user.click(within(sheet).getByRole('button', { expanded: false }));
      await user.click(within(sheet).getByRole('button', { name: 'Повторить' }));

      expect(await within(sheet).findByRole('alert')).toHaveTextContent(
        'Этот отказ повтором не чинится.',
      );
    });

    it('«Подробнее» грузит задание только по нажатию и показывает код, задание и события', async () => {
      const user = userEvent.setup();
      mocks.pipeline.mockResolvedValue({ data: pipelineWith([failedSheet]) });
      mocks.readJob.mockResolvedValue({
        data: {
          job_id: 'job-f',
          revision_id: 'rev-1',
          attempt: 1,
          status: 'failed',
          stage: 'convert',
          error_code: 'CAD_ENGINE_FAILED',
          error_message: 'engine exited with code 3',
          finished_at: '2026-11-11T10:01:00Z',
        },
      });
      mocks.events.mockResolvedValue({
        data: {
          job_id: 'job-f',
          attempt: 1,
          last_seq: 1,
          finished: true,
          events: [
            { seq: 1, attempt: 1, at: '2026-11-11T10:00:30Z', scope: 'document', status: 'error', detail: 'сбой движка' },
          ],
        },
      });
      renderPanel(panel());

      const sheet = (await screen.findByText('Лист 2')).closest('li') as HTMLElement;
      await user.click(within(sheet).getByRole('button', { expanded: false }));
      expect(mocks.readJob).not.toHaveBeenCalled();

      await user.click(within(sheet).getByRole('button', { name: 'Подробнее' }));
      expect(await within(sheet).findByText('engine exited with code 3')).toBeInTheDocument();
      expect(within(sheet).getAllByText('CAD_ENGINE_FAILED').length).toBeGreaterThan(0);
      expect(within(sheet).getByText('job-f')).toBeInTheDocument();
      expect(await within(sheet).findByText(/сбой движка/)).toBeInTheDocument();
      expect(within(sheet).getByRole('button', { name: 'Копировать' })).toBeInTheDocument();
    });

    it('«Преобразовать заново» у готового CAD - только после подтверждения', async () => {
      const user = userEvent.setup();
      mocks.pipeline.mockResolvedValue({
        data: pipelineWith([
          { page_index: 0, page_label: '1', calibrated: true, convert: stage(), views: [] },
        ]),
      });
      mocks.createJob.mockResolvedValue({
        data: { job_id: 'job-new', requested_pages: [0] },
      });
      renderPanel(panel());

      const sheet = (await screen.findByText('Лист 1')).closest('li') as HTMLElement;
      await user.click(within(sheet).getByRole('button', { expanded: false }));
      await user.click(within(sheet).getByRole('button', { name: 'Преобразовать заново' }));
      expect(mocks.createJob).not.toHaveBeenCalled();

      const dialog = await screen.findByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: 'Преобразовать заново' }));
      await waitFor(() => expect(mocks.createJob).toHaveBeenCalledTimes(1));
      expect(mocks.createJob.mock.calls[0]?.[0]).toMatchObject({
        path: { project_id: 'p-1', revision_id: 'rev-1' },
        body: { pages: [0] },
      });
    });
  });
});
