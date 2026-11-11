import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { floor3dFixture } from '@/lib/cad/floor3d-fixtures';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadFloor3dDxfButton } from './CadFloor3dDxfButton';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  createCadFloor3dDxf: vi.fn(),
  readJob: vi.fn(),
}));

const params: ICadViewParams = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'j1',
  attempt: 1,
  pageIndex: 2,
  view: 1,
};

const model = floor3dFixture();

const posted = (status: string) =>
  Promise.resolve({
    data: { job_id: 'dxf1', status, attempt: 1, created_at: '', page_index: 2, parent_job_id: 'j1', view: 1 },
  }) as never;

const job = (status: string, extra: Record<string, unknown> = {}) =>
  Promise.resolve({ data: { id: 'dxf1', status, error_code: null, error_message: null, ...extra } }) as never;

const mount = (hasCandidates = false, title?: client.CadSheetFloorTitle) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CadFloor3dDxfButton
        params={params}
        model={model}
        title={title}
        disabled={false}
        hasCandidates={hasCandidates}
      />
    </QueryClientProvider>,
  );
};

let clickSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.mocked(client.createCadFloor3dDxf).mockReset();
  vi.mocked(client.readJob).mockReset();
  clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
});

afterEach(() => {
  clickSpy.mockRestore();
  vi.useRealTimers();
});

describe('Скачать 3D DXF', () => {
  it('POST с параметрами вида, опрос до succeeded, автоскачивание и ссылка на артефакт', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(client.createCadFloor3dDxf).mockImplementation(() => posted('queued'));
    vi.mocked(client.readJob)
      .mockImplementationOnce(() => job('running'))
      .mockImplementation(() => job('succeeded'));
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Скачать 3D DXF' }));
    expect(client.createCadFloor3dDxf).toHaveBeenCalledWith(
      expect.objectContaining({ path: { project_id: 'p1', job_id: 'j1', page_index: 2, view: 1 } }),
    );
    expect(await screen.findByRole('button', { name: 'Готовим DXF…' })).toBeDisabled();
    await waitFor(() => expect(client.readJob).toHaveBeenCalledWith(expect.objectContaining({ path: { job_id: 'dxf1' } })));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    const link = await screen.findByRole('link', { name: 'Скачать ещё раз' });
    expect(link.getAttribute('href')).toMatch(
      /\/api\/v1\/projects\/p1\/revisions\/r1\/cad\/dxf1\/artifacts\/views\/p003_v01\/floor3d\.dxf$/,
    );
    expect(link).toHaveAttribute('download', 'floor3d_p3_v1.dxf');
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it('повтор той же модели уже готов - без опроса, второго POST нет', async () => {
    vi.mocked(client.createCadFloor3dDxf).mockImplementation(() => posted('succeeded'));
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Скачать 3D DXF' }));
    await screen.findByRole('link', { name: 'Скачать ещё раз' });
    expect(client.readJob).not.toHaveBeenCalled();
    expect(client.createCadFloor3dDxf).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: 'Скачать 3D DXF' })).toBeNull();
  });

  it('failed - текст ошибки задания и «Повторить»', async () => {
    vi.mocked(client.createCadFloor3dDxf).mockImplementation(() => posted('failed'));
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Скачать 3D DXF' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    vi.mocked(client.createCadFloor3dDxf).mockImplementation(() => posted('succeeded'));
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await screen.findByRole('link', { name: 'Скачать ещё раз' });
    expect(client.createCadFloor3dDxf).toHaveBeenCalledTimes(2);
  });

  it('failed при опросе показывает ошибку задания по-русски', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(client.createCadFloor3dDxf).mockImplementation(() => posted('queued'));
    vi.mocked(client.readJob).mockImplementation(() =>
      job('failed', { error_code: 'CAD_ENGINE_FAILED', error_message: 'boom' }),
    );
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Скачать 3D DXF' }));
    expect(await screen.findByText('Движок CAD не выдал проверенный результат.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeEnabled();
  });

  it('подсказка про отверстия-кандидаты', () => {
    mount(true);
    expect(screen.getByText('Отверстия-кандидаты войдут в DXF как отверстия')).toBeInTheDocument();
  });

  it('имя файла по заголовку плана: floor3d_K9_S3_14.dxf', async () => {
    vi.mocked(client.createCadFloor3dDxf).mockImplementation(() => posted('succeeded'));
    mount(false, { corps: '9', section: '3', floors: ['14'] });
    fireEvent.click(screen.getByRole('button', { name: 'Скачать 3D DXF' }));
    const link = await screen.findByRole('link', { name: 'Скачать ещё раз' });
    expect(link).toHaveAttribute('download', 'floor3d_K9_S3_14.dxf');
  });
});
