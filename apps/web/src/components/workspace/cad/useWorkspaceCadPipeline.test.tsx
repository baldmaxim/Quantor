import type * as ApiClient from '@quantor/api-client';
import type { CadPipelineRead, CadPipelineSheetRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ pipeline: vi.fn(), zonesAuto: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readCadPipeline: mocks.pipeline,
  startCadZonesAuto: mocks.zonesAuto,
}));

import { pipelineSheet, pipelineView, stage } from './pipeline-fixtures';
import { useWorkspaceCadPipeline } from './useWorkspaceCadPipeline';

const read = (sheets: CadPipelineSheetRead[]): CadPipelineRead => ({
  revision_id: 'r1',
  server_time: '2026-11-11T10:00:00Z',
  sheets,
});

const setup = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    () => useWorkspaceCadPipeline({ projectId: 'p1', revisionId: 'r1', pageIndex: 2, enabled: true }),
    { wrapper },
  );
  return { client, invalidate, hook };
};

const keysOf = (spy: { mock: { calls: readonly (readonly unknown[])[] } }): unknown[][] =>
  spy.mock.calls.map((call) => (call[0] as { queryKey: unknown[] }).queryKey);

const running = pipelineSheet({
  views: [
    pipelineView({
      walls: stage({ job_id: 'w1', job_type: 'cad_walls', status: 'running', progress: 0.3 }),
      zones: stage({ job_id: 'z1', job_type: 'cad_zones' }),
    }),
  ],
});

describe('useWorkspaceCadPipeline', () => {
  beforeEach(() => {
    mocks.pipeline.mockReset();
    mocks.zonesAuto.mockReset();
  });

  it('выбирает лист по индексу страницы; листа нет - sheet null, шаги с чистого листа', async () => {
    mocks.pipeline.mockResolvedValue({ data: read([pipelineSheet({ page_index: 5 })]) });
    const { hook } = setup();
    await waitFor(() => expect(hook.result.current.isPending).toBe(false));
    expect(hook.result.current.sheet).toBeNull();
    expect(hook.result.current.summary).toBeNull();
    expect(hook.result.current.steps[0]).toMatchObject({ key: 'calibration', state: 'todo' });
  });

  it('конструкции закончились: сбрасываются конструкции, 3D и конвейер', async () => {
    mocks.pipeline.mockResolvedValueOnce({ data: read([running]) });
    const { hook, invalidate } = setup();
    await waitFor(() => expect(hook.result.current.sheet).not.toBeNull());
    expect(keysOf(invalidate)).not.toContainEqual(['cad-constructions', 'p1', 'r1']);

    mocks.pipeline.mockResolvedValueOnce({ data: read([pipelineSheet()]) });
    await act(async () => {
      await hook.result.current.refetch();
    });
    await waitFor(() => expect(keysOf(invalidate)).toContainEqual(['cad-constructions', 'p1', 'r1']));
    expect(keysOf(invalidate)).toContainEqual(['cad-floor3d', 'p1', 'r1']);
    expect(keysOf(invalidate)).toContainEqual(['cad', 'p1', 'r1', 'pipeline']);
  });

  it('зоны закончились: сбрасываются зоны ревизии; преобразование - список заданий', async () => {
    const zonesRunning = pipelineSheet({
      convert: stage({ job_id: 'c1', status: 'running', progress: 0.5 }),
      views: [pipelineView({ zones: stage({ job_id: 'z1', job_type: 'cad_zones', status: 'running' }) })],
    });
    mocks.pipeline.mockResolvedValueOnce({ data: read([zonesRunning]) });
    const { hook, invalidate } = setup();
    await waitFor(() => expect(hook.result.current.sheet).not.toBeNull());

    mocks.pipeline.mockResolvedValueOnce({ data: read([pipelineSheet()]) });
    await act(async () => {
      await hook.result.current.refetch();
    });
    await waitFor(() => expect(keysOf(invalidate)).toContainEqual(['cad', 'p1', 'r1', 'zones']));
    expect(keysOf(invalidate)).toContainEqual(['cad', 'p1', 'r1', 'jobs']);
  });

  it('ничего не менялось: запросы не сбрасываются', async () => {
    mocks.pipeline.mockResolvedValue({ data: read([pipelineSheet()]) });
    const { hook, invalidate } = setup();
    await waitFor(() => expect(hook.result.current.sheet).not.toBeNull());
    await act(async () => {
      await hook.result.current.refetch();
    });
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('startAutoZones: пост на задание преобразования и первый вид с DXF, затем сброс конвейера', async () => {
    const sheet = pipelineSheet({
      views: [
        pipelineView({ page: 2, view: 0, has_dxf: false, zones: null, zones_count: 0 }),
        pipelineView({ page: 2, view: 1, has_dxf: true, zones: null, zones_count: 0 }),
      ],
    });
    mocks.pipeline.mockResolvedValue({ data: read([sheet]) });
    mocks.zonesAuto.mockResolvedValue({ data: { job_id: 'zj' } });
    const { hook, invalidate } = setup();
    await waitFor(() => expect(hook.result.current.sheet).not.toBeNull());

    await act(async () => {
      await hook.result.current.startAutoZones();
    });
    expect(mocks.zonesAuto).toHaveBeenCalledTimes(1);
    expect(mocks.zonesAuto.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1', job_id: 'job-1', page_index: 2, view: 1 },
    });
    expect(hook.result.current.zonesError).toBeNull();
    expect(keysOf(invalidate)).toContainEqual(['cad', 'p1', 'r1', 'pipeline']);
  });

  it('409 CAD_ZONES_NOT_EMPTY: текст отказа в zonesError', async () => {
    mocks.pipeline.mockResolvedValue({ data: read([pipelineSheet()]) });
    mocks.zonesAuto.mockRejectedValue({ detail: { code: 'CAD_ZONES_NOT_EMPTY' } });
    const { hook } = setup();
    await waitFor(() => expect(hook.result.current.sheet).not.toBeNull());

    await act(async () => {
      await hook.result.current.startAutoZones();
    });
    expect(hook.result.current.zonesError).toBe(
      'На виде уже есть зоны — автоматическая разметка не запускается.',
    );
    expect(hook.result.current.startingZones).toBe(false);
  });
});
