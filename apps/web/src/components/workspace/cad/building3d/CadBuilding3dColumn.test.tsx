import * as client from '@quantor/api-client';
import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CadBuilding3dColumn } from './CadBuilding3dColumn';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readCadBuilding3D: vi.fn(),
}));

// Холст three.js в jsdom не нужен (нет WebGL): подставка отдаёт «щелчок по этажу» с известным ключом.
vi.mock('./CadBuilding3dCanvas', () => ({
  CadBuilding3dCanvas: ({
    currentKey,
    onSelect,
  }: {
    currentKey: string | null;
    onSelect: (key: string) => void;
  }) => (
    <button type="button" data-current={currentKey ?? ''} onClick={() => onSelect('j2:0:0')}>
      щелчок по холсту
    </button>
  ),
}));

const rect: number[][] = [
  [0, 0],
  [10000, 0],
  [10000, 6000],
  [0, 6000],
];

const floor = (patch: Partial<CadBuilding3dFloorRead>): CadBuilding3dFloorRead => ({
  job_id: 'j1',
  revision_id: 'r1',
  document_id: 'd1',
  page_index: 0,
  view: 0,
  label: '1 этаж',
  elevation_known: true,
  base_z_mm: 0,
  floor_height_mm: 3000,
  floor_height_known: true,
  slab_thickness_mm: 200,
  slab_thickness_known: true,
  outline: rect,
  outline_source: 'slab',
  bbox: null,
  corps: null,
  section: null,
  group_key: 'none',
  group_label: 'Корпус не указан',
  offset_mm: [0, 0],
  alignment: 'reference',
  alignment_axes: [],
  alignment_message: null,
  ...patch,
});

const respond = (floors: CadBuilding3dFloorRead[], groups: CadBuilding3dGroupRead[] = []) =>
  vi.mocked(client.readCadBuilding3D).mockImplementation(
    () => Promise.resolve({ data: { floors, groups, units: 'mm', warnings: [] } }) as never,
  );

const group = (key: string, label: string, floorCount: number): CadBuilding3dGroupRead => ({
  key,
  label,
  floor_count: floorCount,
  aligned_count: floorCount,
});

const mount = (onSelectFloor = vi.fn()) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CadBuilding3dColumn
        projectId="p1"
        current={{ jobId: 'j1', pageIndex: 0, view: 0 }}
        onSelectFloor={onSelectFloor}
      />
    </QueryClientProvider>,
  );
  return onSelectFloor;
};

beforeEach(() => {
  vi.mocked(client.readCadBuilding3D).mockReset();
});

describe('колонка «Здание»', () => {
  it('показывает список сверху вниз, этажи без отметки - внизу', async () => {
    respond([
      floor({ job_id: 'j1', label: '1 этаж', base_z_mm: 0 }),
      floor({ job_id: 'j2', label: '2 этаж', base_z_mm: 3000 }),
      floor({ job_id: 'j3', label: 'Кровля', elevation_known: false }),
    ]);
    mount();
    const rows = within(await screen.findByRole('list')).getAllByRole('button');
    expect(rows.map((row) => row.textContent)).toEqual([
      '2 этаж+3.000',
      '1 этаж0.000',
      'Кровляотметка не определена',
    ]);
    expect(rows[1]).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('button', { name: 'щелчок по холсту' })).toHaveAttribute(
      'data-current',
      'j1:0:0',
    );
  });

  it('выбор этажа в списке и на холсте отдаёт этаж', async () => {
    respond([floor({ job_id: 'j1' }), floor({ job_id: 'j2', label: '2 этаж', base_z_mm: 3000 })]);
    const onSelectFloor = mount();
    fireEvent.click(await screen.findByRole('button', { name: /2 этаж/ }));
    expect(onSelectFloor).toHaveBeenLastCalledWith(expect.objectContaining({ job_id: 'j2' }));
    fireEvent.click(screen.getByRole('button', { name: 'щелчок по холсту' }));
    expect(onSelectFloor).toHaveBeenCalledTimes(2);
  });

  it('пустое состояние', async () => {
    respond([]);
    mount();
    await waitFor(() => expect(screen.getByText('Нет листов с конструкциями')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'щелчок по холсту' })).toBeNull();
  });

  it('без отметок нигде - холста нет, список есть', async () => {
    respond([floor({ elevation_known: false, label: 'Лист А' })]);
    mount();
    expect(await screen.findByText(/нечего строить/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Лист А/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'щелчок по холсту' })).toBeNull();
  });

  describe('здания', () => {
    const two = () =>
      respond(
        [
          floor({ job_id: 'a1', label: 'К2 этаж 1', group_key: 'k2', group_label: 'Корп. 2' }),
          floor({
            job_id: 'a2',
            label: 'К2 этаж 2',
            base_z_mm: 3000,
            group_key: 'k2',
            group_label: 'Корп. 2',
            alignment: 'axes',
            alignment_axes: ['3.1', '3.2', 'А'],
          }),
          floor({
            job_id: 'b1',
            label: 'К10 этаж 1',
            group_key: 'k10',
            group_label: 'Корп. 10',
          }),
        ],
        [group('k2', 'Корп. 2', 2), group('k10', 'Корп. 10', 1)],
      );

    it('по умолчанию показывает первое здание, переключатель меняет список', async () => {
      two();
      mount();
      const select = await screen.findByRole('combobox', { name: /Корпус и секция/ });
      expect(select).toHaveValue('k2');
      expect(
        within(screen.getByRole('list')).getAllByRole('button').map((row) => row.textContent),
      ).toEqual(['К2 этаж 2по осям 3.1, 3.2, А+3.000', 'К2 этаж 10.000']);
      fireEvent.change(select, { target: { value: 'k10' } });
      expect(
        within(screen.getByRole('list')).getAllByRole('button').map((row) => row.textContent),
      ).toEqual(['К10 этаж 10.000']);
    });

    it('одно здание - переключателя нет', async () => {
      respond([floor({ group_key: 'k2' })], [group('k2', 'Корп. 2', 1)]);
      mount();
      await screen.findByRole('list');
      expect(screen.queryByRole('combobox')).toBeNull();
    });

    it('этаж без совмещения помечен с пояснением, если в здании больше одного этажа', async () => {
      respond(
        [
          floor({ job_id: 'a1', label: 'Эталон', group_key: 'k2' }),
          floor({
            job_id: 'a2',
            label: 'Сдвинутый',
            base_z_mm: 3000,
            group_key: 'k2',
            alignment: 'none',
            alignment_message: 'нет общих осей с эталонным этажом',
          }),
          floor({
            job_id: 'b1',
            label: 'Одиночный',
            group_key: 'k10',
            alignment: 'none',
            alignment_message: 'в группе нет этажа с осями',
          }),
        ],
        [group('k2', 'Корп. 2', 2), group('k10', 'Корп. 10', 1)],
      );
      mount();
      const row = await screen.findByRole('button', { name: /Сдвинутый/ });
      expect(row).toHaveTextContent('не совмещён по осям');
      expect(row).toHaveAttribute('title', 'нет общих осей с эталонным этажом');
      fireEvent.change(screen.getByRole('combobox'), { target: { value: 'k10' } });
      expect(screen.getByRole('button', { name: /Одиночный/ })).not.toHaveTextContent('не совмещён');
    });
  });
});
