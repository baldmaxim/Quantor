import type * as ApiClient from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ recompute: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  recomputeCadWalls: api.recompute,
}));

vi.mock('./WorkspaceCadConvert', () => ({
  WorkspaceCadConvert: (props: { pageIndex: number; again?: boolean; currentJobId?: string | null }) => (
    <div data-testid="convert-stub">
      {props.again ? `заново ${props.currentJobId ?? ''}` : `запуск листа ${props.pageIndex}`}
    </div>
  ),
}));

import { pipelineOfSheet, pipelineSheet, pipelineView, stage } from './pipeline-fixtures';
import type { IWorkspaceCadConvert } from './types';
import { WorkspaceCadPipeline } from './WorkspaceCadPipeline';

const CONVERT: IWorkspaceCadConvert = {
  projectId: 'p',
  revisionId: 'r',
  sheetId: 's',
  pageIndex: 2,
  onCalibrate: vi.fn(),
  onJobCreated: vi.fn(),
};

const mount = (
  pipeline: ReturnType<typeof pipelineOfSheet>,
  extra: { openablePanels?: string[]; onOpenPanel?: (id: string) => void } = {},
) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
      <WorkspaceCadPipeline
        pipeline={pipeline}
        convert={CONVERT}
        openablePanels={extra.openablePanels ?? ['mep', 'constructions']}
        onOpenPanel={extra.onOpenPanel ?? vi.fn()}
      />
    </QueryClientProvider>,
  );

beforeEach(() => {
  api.recompute.mockReset();
  api.recompute.mockResolvedValue({ data: { job_id: 'w2' } });
});

describe('WorkspaceCadPipeline', () => {
  it('семь шагов со словом состояния и подсказкой под списком', () => {
    mount(pipelineOfSheet(pipelineSheet()));
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(7);
    expect(items[0]).toHaveTextContent('Калибровкаготово');
    expect(items[3]).toHaveTextContent('Зоныготово');
    expect(items[4]).toHaveTextContent('Одобрениенужно решение');
    expect(
      screen.getByText(/Конструкции и зоны считаются сами после преобразования/),
    ).toBeInTheDocument();
  });

  it('нет калибровки: запуск и калибровка из WorkspaceCadConvert под шагом «Калибровка»', () => {
    mount(pipelineOfSheet(null));
    const stub = screen.getByTestId('convert-stub');
    expect(screen.getAllByTestId('convert-stub')).toHaveLength(1);
    expect(screen.getAllByRole('listitem')[0]).toContainElement(stub);
  });

  it('калибровка есть, преобразования не было: запуск под шагом «CAD», один раз', () => {
    mount(pipelineOfSheet(pipelineSheet({ convert: null, views: [] })));
    expect(screen.getAllByTestId('convert-stub')).toHaveLength(1);
    expect(screen.getAllByRole('listitem')[1]).toContainElement(screen.getByTestId('convert-stub'));
  });

  it('лист преобразован: «заново» под шагом «CAD» с id текущего задания', () => {
    mount(pipelineOfSheet(pipelineSheet({ convert: stage({ job_id: 'conv-7' }) })));
    const stub = screen.getByTestId('convert-stub');
    expect(screen.getAllByTestId('convert-stub')).toHaveLength(1);
    expect(screen.getAllByRole('listitem')[1]).toContainElement(stub);
    expect(stub).toHaveTextContent('заново conv-7');
  });

  it('преобразования не было: обычный запуск, режима «заново» нет', () => {
    mount(pipelineOfSheet(pipelineSheet({ convert: null, views: [] })));
    expect(screen.getByTestId('convert-stub')).toHaveTextContent('запуск листа 2');
    expect(screen.queryByText(/заново/)).toBeNull();
  });

  it('преобразование упало: запуск заново под шагом «CAD»', () => {
    mount(
      pipelineOfSheet(
        pipelineSheet({ convert: stage({ status: 'failed', error_code: 'CAD_ENGINE_FAILED' }), views: [] }),
      ),
    );
    const item = screen.getAllByRole('listitem')[1];
    expect(item).toContainElement(screen.getByTestId('convert-stub'));
    expect(item).toHaveTextContent('Движок CAD не выдал проверенный результат.');
  });

  it('конструкции упали: «Открыть Конструкции» открывает раздел', () => {
    const onOpenPanel = vi.fn();
    const view = pipelineView({ walls: stage({ job_id: 'w1', status: 'failed', error_code: 'CAD_ENGINE_FAILED' }) });
    mount(pipelineOfSheet(pipelineSheet({ views: [view] })), { onOpenPanel });
    fireEvent.click(screen.getByRole('button', { name: 'Открыть Конструкции' }));
    expect(onOpenPanel).toHaveBeenCalledWith('constructions');
  });

  it('конструкции упали: «Повторить» пересчитывает упавший вид', async () => {
    const view = pipelineView({
      view: 1,
      walls: stage({ job_id: 'w1', job_type: 'cad_walls', status: 'failed', error_code: 'CAD_ENGINE_FAILED' }),
    });
    mount(pipelineOfSheet(pipelineSheet({ convert: stage({ job_id: 'conv-7' }), views: [view] })));
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(api.recompute).toHaveBeenCalledTimes(1));
    expect(api.recompute.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p', job_id: 'conv-7', page_index: 2, view: 1 },
    });
  });

  it('несколько видов: пересчёт только у упавших; отказ сервера показан', async () => {
    const failed = stage({ job_id: 'w1', job_type: 'cad_walls', status: 'failed' });
    const views = [
      pipelineView({ view: 0, walls: failed }),
      pipelineView({ view: 1 }),
      pipelineView({ view: 2, walls: failed }),
    ];
    api.recompute.mockRejectedValue({ detail: { code: 'CAD_WALLS_BUSY' } });
    mount(pipelineOfSheet(pipelineSheet({ views })));
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    const sent = api.recompute.mock.calls.map((call) => (call[0] as { path: { view: number } }).path.view);
    expect(sent.sort()).toEqual([0, 2]);
  });

  it('конструкции не упали: «Повторить» нет', () => {
    mount(pipelineOfSheet(pipelineSheet()));
    expect(screen.queryByRole('button', { name: 'Повторить' })).toBeNull();
  });

  it('зон нет и задания не было: «Разметить зоны автоматически» запускает разметку', () => {
    const startAutoZones = vi.fn(() => Promise.resolve());
    const view = pipelineView({ zones: null, zones_count: 0 });
    mount(pipelineOfSheet(pipelineSheet({ views: [view] }), { startAutoZones }));
    fireEvent.click(screen.getByRole('button', { name: 'Разметить зоны автоматически' }));
    expect(startAutoZones).toHaveBeenCalledTimes(1);
  });

  it('разметка зон упала: кнопка есть, текст отказа показан', () => {
    const view = pipelineView({ zones: stage({ job_id: 'z1', status: 'failed' }) });
    mount(
      pipelineOfSheet(pipelineSheet({ views: [view] }), {
        zonesError: 'На виде уже есть зоны — автоматическая разметка не запускается.',
      }),
    );
    expect(screen.getByRole('button', { name: 'Разметить зоны автоматически' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('На виде уже есть зоны');
  });

  it('конструкции и зоны готовы: «Перейти к одобрению» открывает «Трассы»', () => {
    const onOpenPanel = vi.fn();
    mount(pipelineOfSheet(pipelineSheet()), { onOpenPanel });
    fireEvent.click(screen.getByRole('button', { name: 'Перейти к одобрению' }));
    expect(onOpenPanel).toHaveBeenCalledWith('mep');
    expect(screen.queryByRole('button', { name: 'Проверить трассы' })).toBeNull();
  });

  it('трассы ждут принятия: «Проверить трассы»', () => {
    const onOpenPanel = vi.fn();
    const view = pipelineView({
      approved: true,
      routes: stage({ job_id: 'rt1', job_type: 'cad_mep_route' }),
    });
    mount(pipelineOfSheet(pipelineSheet({ views: [view] })), { onOpenPanel });
    fireEvent.click(screen.getByRole('button', { name: 'Проверить трассы' }));
    expect(onOpenPanel).toHaveBeenCalledWith('mep');
  });

  it('раздела «Трассы» нет: действие не показывается', () => {
    mount(pipelineOfSheet(pipelineSheet()), { openablePanels: [] });
    expect(screen.queryByRole('button', { name: 'Перейти к одобрению' })).toBeNull();
  });

  it('идущий шаг: ход показан, кнопок нет', () => {
    const view = pipelineView({
      walls: stage({ job_id: 'w1', status: 'running', progress: 0.4 }),
      zones: stage({ job_id: 'z1', status: 'queued', progress: null }),
    });
    mount(pipelineOfSheet(pipelineSheet({ views: [view] })));
    expect(screen.getByText('40 %')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('загрузка: скелетон; отказ: повтор и запуск остаётся', () => {
    const { unmount } = mount(pipelineOfSheet(null, { isPending: true }));
    expect(screen.getByRole('status', { name: 'Загрузка обработки листа' })).toBeInTheDocument();
    unmount();
    const refetch = vi.fn();
    mount(pipelineOfSheet(null, { isError: true, refetch }));
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('convert-stub')).toBeInTheDocument();
  });

  it('лист с заголовком плана подписан этажом, без заголовка подписи нет', () => {
    const { unmount } = mount(
      pipelineOfSheet(
        pipelineSheet({
          page_label: '82',
          floor_title: { corps: '9', section: '3', floors: ['15'], text: null },
        }),
      ),
    );
    const title = screen.getByTestId('pipeline-floor-title');
    expect(title).toHaveTextContent('К9 · С3 · 15 эт.');
    expect(title).toHaveTextContent('Лист 82');
    expect(title).toHaveAttribute('title', 'Корпус 9, секция 3, 15 этаж');
    unmount();
    mount(pipelineOfSheet(pipelineSheet()));
    expect(screen.queryByTestId('pipeline-floor-title')).toBeNull();
  });
});
