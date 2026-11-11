import * as client from '@quantor/api-client';
import type { CadBuilding3dFloorRead } from '@quantor/api-client';
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
  ...patch,
});

const respond = (floors: CadBuilding3dFloorRead[]) =>
  vi.mocked(client.readCadBuilding3D).mockImplementation(
    () => Promise.resolve({ data: { floors, units: 'mm', warnings: [] } }) as never,
  );

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
});
