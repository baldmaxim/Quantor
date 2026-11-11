import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { templateFixture } from '@/components/cad/finishes/finish-fixtures';
import { zoneFixture } from '@/components/cad/viewer/zoneModeTestUtils';
import { Camera } from '@/lib/viewer/camera';

const api = vi.hoisted(() => ({
  listCadZones: vi.fn(),
  updateCadZone: vi.fn(),
  listCadFinishTemplates: vi.fn(),
  assignCadFinishTemplate: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { useWorkspaceCadZones } from './useWorkspaceCadZones';

const mount = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    () =>
      useWorkspaceCadZones({
        projectId: 'p1',
        revisionId: 'r1',
        pageIndex: 0,
        pageSize: { width: 1000, height: 1000 },
        camera: new Camera(),
        load: true,
        active: true,
        remarksCapturing: false,
      }),
    { wrapper },
  );
  return { ...hook, invalidate };
};

describe('отделка в зонах листа', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listCadZones.mockResolvedValue({ data: [zoneFixture({ id: 'a' })] });
    api.listCadFinishTemplates.mockResolvedValue({ data: [templateFixture({ id: 't1' })] });
  });

  it('шаблоны проекта доступны списку зон', async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.zones.finish?.templates).toHaveLength(1));
    expect(result.current.zones.finish?.templates[0]?.id).toBe('t1');
  });

  it('смена типа помещения - PATCH room_type, затем перечитываются зоны и ведомость', async () => {
    api.updateCadZone.mockResolvedValue({ data: zoneFixture({ id: 'a', room_type: 'corridor' }) });
    const { result, invalidate } = mount();
    await waitFor(() => expect(result.current.zones.zones).toHaveLength(1));
    act(() => result.current.zones.onSetRoomType?.('a', 'corridor'));
    await waitFor(() => expect(api.updateCadZone).toHaveBeenCalled());
    expect(api.updateCadZone.mock.calls[0]?.[0]).toMatchObject({
      path: { zone_id: 'a' },
      body: { room_type: 'corridor' },
    });
    await waitFor(() =>
      expect(invalidate.mock.calls.map((call) => call[0]?.queryKey)).toContainEqual([
        'cad',
        'p1',
        'r1',
        'finishes',
      ]),
    );
  });

  it('назначение: POST finish-assign, результат - назначено и пропущено', async () => {
    api.assignCadFinishTemplate.mockResolvedValue({
      data: { assigned: 1, skipped_count: 1, skipped: [{ zone_id: 'd', reason: 'door' }] },
    });
    const { result } = mount();
    await waitFor(() => expect(result.current.zones.finish).toBeTruthy());
    let outcome: unknown = null;
    await act(async () => {
      outcome = await result.current.zones.finish?.onAssign(['a', 'd'], 't1');
    });
    expect(outcome).toEqual({ assigned: 1, skipped: 1 });
    expect(api.assignCadFinishTemplate.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1' },
      body: { zone_ids: ['a', 'd'], template_id: 't1' },
    });
  });

  it('снятие явного назначения - template_id null', async () => {
    api.assignCadFinishTemplate.mockResolvedValue({
      data: { assigned: 1, skipped_count: 0, skipped: [] },
    });
    const { result } = mount();
    await waitFor(() => expect(result.current.zones.finish).toBeTruthy());
    await act(async () => {
      await result.current.zones.finish?.onAssign(['a'], null);
    });
    expect(api.assignCadFinishTemplate.mock.calls[0]?.[0]).toMatchObject({
      body: { zone_ids: ['a'], template_id: null },
    });
  });

  it('отказ назначения: null и текст ошибки', async () => {
    api.assignCadFinishTemplate.mockRejectedValue({
      detail: { code: 'FEATURE_DISABLED', message: 'x' },
    });
    const { result } = mount();
    await waitFor(() => expect(result.current.zones.finish).toBeTruthy());
    let outcome: unknown = 'не вызвано';
    await act(async () => {
      outcome = await result.current.zones.finish?.onAssign(['a'], 't1');
    });
    expect(outcome).toBeNull();
    await waitFor(() =>
      expect(result.current.zones.finish?.error).toBe(
        'Эта возможность выключена для пространства.',
      ),
    );
  });
});
