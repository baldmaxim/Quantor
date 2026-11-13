import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { floorKey } from '@/lib/cad/building3d-geometry';

import { BuildingViewer, type IBuildingViewerSelection } from './BuildingViewer';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readCadBuilding3D: vi.fn(),
  readCadJob: vi.fn(),
  readCadConstructions: vi.fn(),
}));

// WebGL в jsdom нет: холст и детальный вид - подставки.
vi.mock('./BuildingViewerCanvas', () => ({
  BuildingViewerCanvas: ({
    selectedKey,
    exploded,
    onSelect,
    onOpenDetail,
  }: {
    selectedKey: string | null;
    exploded: boolean;
    onSelect: (key: string) => void;
    onOpenDetail: (key: string) => void;
  }) => (
    <div data-testid="canvas" data-selected={selectedKey ?? ''} data-exploded={String(exploded)}>
      <button type="button" onClick={() => onSelect('j1:0:0')}>
        щелчок по этажу
      </button>
      <button type="button" onClick={() => onOpenDetail('j1:0:0')}>
        двойной щелчок по этажу
      </button>
    </div>
  ),
}));
vi.mock('@/components/workspace/cad/floor3d/CadFloor3dLazy', () => ({
  CadFloor3dLazy: ({ readOnly }: { readOnly?: boolean }) => (
    <div data-testid="floor3d" data-readonly={String(readOnly)} />
  ),
}));

const wall = { kind: 'masonry' as const, shell: [[0, 0], [1000, 0], [1000, 200], [0, 200]] };

const floor = (patch: Partial<client.CadBuilding3dFloorRead> = {}): client.CadBuilding3dFloorRead => ({
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
  slab_thickness_known: false,
  outline: [[0, 0], [10000, 0], [10000, 6000], [0, 6000]],
  outline_source: 'slab',
  bbox: null,
  corps: '9',
  section: '3',
  group_key: 'k9s3',
  group_label: 'К9 · С3',
  offset_mm: [0, 0],
  alignment: 'reference',
  alignment_axes: [],
  alignment_message: null,
  walls: [wall, { ...wall, kind: 'monolith_wall' }],
  ...patch,
});

const mount = (selection: IBuildingViewerSelection, onSelectionChange = vi.fn()) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <BuildingViewer
        projectId="p1"
        selection={selection}
        onSelectionChange={onSelectionChange}
        onOpenSheet={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return onSelectionChange;
};

const NOTHING: IBuildingViewerSelection = { floor: null, detail: false };

beforeEach(() => {
  vi.mocked(client.readCadBuilding3D).mockResolvedValue({
    data: {
      floors: [floor(), floor({ job_id: 'j2', label: '2 этаж', base_z_mm: 3000 }), floor({ job_id: 'j3', label: 'Кровля', elevation_known: false })],
      groups: [{ key: 'k9s3', label: 'К9 · С3', floor_count: 3 }],
      warnings: [],
    },
  } as never);
  vi.mocked(client.readCadJob).mockResolvedValue({
    data: { job_id: 'j1', revision_id: 'r1', result_attempt: 2, result_status: 'no_cad_review_required', pages: [] },
  } as never);
  vi.mocked(client.readCadConstructions).mockRejectedValue({ detail: { code: 'CAD_WALLS_NOT_READY' } });
});

describe('Просмотрщик объекта', () => {
  it('запрашивает здание со стенами; ничего не выбрано - подсказка', async () => {
    mount(NOTHING);
    expect(await screen.findByText('Нажмите на этаж')).toBeInTheDocument();
    expect(client.readCadBuilding3D).toHaveBeenCalledWith(
      expect.objectContaining({ path: { project_id: 'p1' }, query: { walls: true } }),
    );
  });

  it('этаж без отметки - в списке внизу с пометкой', async () => {
    mount(NOTHING);
    await screen.findByText('Кровля');
    const list = screen.getAllByRole('button').filter((row) => row.closest('ul') !== null);
    expect(list[list.length - 1]).toHaveTextContent('Кровля');
    expect(list[list.length - 1]).toHaveTextContent('отметка не определена');
  });

  it('выбор из списка идёт в адрес', async () => {
    const change = mount(NOTHING);
    fireEvent.click(await screen.findByRole('button', { name: /2 этаж/ }));
    expect(change).toHaveBeenCalledWith({ floor: floorKey({ job_id: 'j2', page_index: 0, view: 0 }), detail: false });
  });

  it('панель этажа: типовая толщина плиты не «0», счёт конструкций по видам', async () => {
    mount({ floor: 'j1:0:0', detail: false });
    expect(await screen.findByText(/не определена, показана типовая \(0,2 м\)/)).toBeInTheDocument();
    expect(screen.getByText('Монолит, конструкций').nextSibling).toHaveTextContent('1');
    expect(screen.getByText('Кладка, конструкций').nextSibling).toHaveTextContent('1');
    expect(await screen.findByText('Конструкции листа ещё не посчитаны.')).toBeInTheDocument();
  });

  it('«Разнести этажи» переключает режим холста', async () => {
    mount(NOTHING);
    await screen.findByTestId('canvas');
    const button = screen.getByRole('button', { name: 'Разнести этажи' });
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-exploded', 'false');
    fireEvent.click(button);
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-exploded', 'true');
    expect(button).toHaveAttribute('aria-pressed', 'true');
  });

  it('двойной щелчок открывает детальный вид в адресе', async () => {
    const change = mount(NOTHING);
    fireEvent.click(await screen.findByRole('button', { name: 'двойной щелчок по этажу' }));
    expect(change).toHaveBeenCalledWith({ floor: 'j1:0:0', detail: true });
  });

  it('детальный вид: этаж только для чтения, «К зданию» снимает режим', async () => {
    const change = mount({ floor: 'j1:0:0', detail: true });
    expect(await screen.findByTestId('floor3d')).toHaveAttribute('data-readonly', 'true');
    expect(screen.queryByRole('button', { name: 'Разнести этажи' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /К зданию/ }));
    expect(change).toHaveBeenCalledWith({ floor: 'j1:0:0', detail: false });
  });
});
