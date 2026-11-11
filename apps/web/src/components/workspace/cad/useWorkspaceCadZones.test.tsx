import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type * as ApiClient from '@quantor/api-client';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { zoneFixture } from '@/components/cad/viewer/zoneModeTestUtils';
import { Camera } from '@/lib/viewer/camera';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  update: vi.fn(),
  create: vi.fn(),
  remove: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  listCadZones: mocks.list,
  updateCadZone: mocks.update,
  createCadZone: mocks.create,
  deleteCadZone: mocks.remove,
}));

import { useWorkspaceCadZones } from './useWorkspaceCadZones';

const PAGE = { width: 1000, height: 1000 };
const camera = new Camera();

const wrapper = ({ children }: { children: ReactNode }) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

type Input = Parameters<typeof useWorkspaceCadZones>[0];
const input = (patch: Partial<Input> = {}): Input => ({
  projectId: 'p1',
  revisionId: 'r1',
  pageIndex: 0,
  pageSize: PAGE,
  camera,
  load: true,
  active: true,
  remarksCapturing: false,
  ...patch,
});

const mount = (patch: Partial<Input> = {}) =>
  renderHook((props: Input) => useWorkspaceCadZones(props), {
    wrapper,
    initialProps: input(patch),
  });

const APARTMENT = zoneFixture({
  id: 'a',
  kind: 'room_apartment',
  apartment_no: '0042',
  name: 'Холл',
});
const DOOR = zoneFixture({
  id: 'd',
  kind: 'door',
  points: [
    [0.1, 0.1],
    [0.2, 0.1],
  ],
});

describe('useWorkspaceCadZones: правка формы зоны', () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.list.mockResolvedValue({ data: [APARTMENT, DOOR] });
  });

  const ready = async (patch: Partial<Input> = {}) => {
    const hook = mount(patch);
    await waitFor(() => expect(hook.result.current.zones.zones).toHaveLength(2));
    return hook;
  };

  it('«Изменить контур» включает режим правки и выбирает зону; рисование выключается', async () => {
    const { result } = await ready();
    act(() => result.current.zones.onStartDrawing());
    expect(result.current.zones.drawing).toBe(false); // не заполнен № квартиры
    act(() => result.current.zones.onStartEdit('a'));
    expect(result.current.edit?.zoneId).toBe('a');
    expect(result.current.split).toBeNull();
    expect(result.current.zones.activeId).toBe('a');
    expect(result.current.zones.shapeEdit).toEqual({ id: 'a', mode: 'edit' });
  });

  it('у двери режимов правки нет', async () => {
    const { result } = await ready();
    act(() => result.current.zones.onStartEdit('d'));
    expect(result.current.edit).toBeNull();
    act(() => result.current.zones.onStartSplit('d'));
    expect(result.current.split).toBeNull();
  });

  it('сохранение правки - PATCH points; успех закрывает режим', async () => {
    mocks.update.mockResolvedValue({ data: APARTMENT });
    const { result } = await ready();
    act(() => result.current.zones.onStartEdit('a'));
    const points: [number, number][] = [
      [0.2, 0.2],
      [0.7, 0.2],
      [0.6, 0.6],
    ];
    act(() => result.current.edit?.onSave(points));
    await waitFor(() => expect(result.current.edit).toBeNull());
    expect(mocks.update.mock.calls[0]?.[0]).toMatchObject({
      path: { zone_id: 'a' },
      body: { points },
    });
  });

  it('отказ сервера при сохранении: режим не закрывается, текст ошибки виден', async () => {
    mocks.update.mockRejectedValue(new Error('Контур пересекает сам себя'));
    const { result } = await ready();
    act(() => result.current.zones.onStartEdit('a'));
    act(() =>
      result.current.edit?.onSave([
        [0.1, 0.1],
        [0.2, 0.2],
        [0.3, 0.1],
      ]),
    );
    await waitFor(() => expect(result.current.edit?.error).not.toBeNull());
    expect(result.current.edit).not.toBeNull();
  });

  it('«Отмена» выходит без запросов; выбор другой зоны тоже выходит', async () => {
    const { result } = await ready();
    act(() => result.current.zones.onStartEdit('a'));
    act(() => result.current.edit?.onCancel());
    expect(result.current.edit).toBeNull();
    expect(mocks.update).not.toHaveBeenCalled();

    act(() => result.current.zones.onStartSplit('a'));
    expect(result.current.split).not.toBeNull();
    act(() => result.current.zones.onActivate('d'));
    expect(result.current.split).toBeNull();
  });

  it('разрез: PATCH большей части в исходную зону, POST меньшей новой зоной; новая выбирается', async () => {
    mocks.update.mockResolvedValue({ data: APARTMENT });
    const added = zoneFixture({ id: 'n', kind: 'room_apartment' });
    mocks.create.mockImplementation(async () => {
      mocks.list.mockResolvedValue({ data: [APARTMENT, DOOR, added] });
      return { data: added };
    });
    const { result } = await ready();
    act(() => result.current.zones.onStartSplit('a'));
    const keep: [number, number][] = [
      [0.3, 0.2],
      [0.6, 0.2],
      [0.6, 0.6],
      [0.3, 0.6],
    ];
    const created: [number, number][] = [
      [0.3, 0.6],
      [0.2, 0.6],
      [0.2, 0.2],
      [0.3, 0.2],
    ];
    act(() => result.current.split?.onApply({ keep, created }));
    await waitFor(() => expect(result.current.zones.activeId).toBe('n'));
    expect(mocks.update.mock.calls[0]?.[0]).toMatchObject({
      path: { zone_id: 'a' },
      body: { points: keep },
    });
    expect(mocks.create.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1' },
      body: {
        revision_id: 'r1',
        page_index: 0,
        kind: 'room_apartment',
        apartment_no: '0042',
        room_mark: null,
        name: 'Холл (2)',
        points: created,
      },
    });
    expect(result.current.split).toBeNull();
  });

  it('разрез: отказ PATCH - вторая зона не создаётся, режим остаётся', async () => {
    mocks.update.mockRejectedValue(new Error('Контур недействителен'));
    const { result } = await ready();
    act(() => result.current.zones.onStartSplit('a'));
    act(() =>
      result.current.split?.onApply({
        keep: [
          [0.3, 0.2],
          [0.6, 0.2],
          [0.6, 0.6],
        ],
        created: [
          [0.2, 0.2],
          [0.3, 0.2],
          [0.3, 0.6],
        ],
      }),
    );
    await waitFor(() => expect(result.current.split?.error).not.toBeNull());
    expect(mocks.create).not.toHaveBeenCalled();
    expect(result.current.split).not.toBeNull();
  });

  it('другая вкладка (active = false) выключает режим', async () => {
    const hook = await ready();
    act(() => hook.result.current.zones.onStartEdit('a'));
    hook.rerender(input({ active: false }));
    expect(hook.result.current.edit).toBeNull();
  });
});
