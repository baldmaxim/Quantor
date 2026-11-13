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
    constructionId,
    allGroups,
    exploded,
    onSelect,
    onSelectConstruction,
    onOpenDetail,
  }: {
    selectedKey: string | null;
    constructionId: string | null;
    allGroups: unknown[] | null;
    exploded: boolean;
    onSelect: (key: string) => void;
    onSelectConstruction: (id: string | null) => void;
    onOpenDetail: (key: string) => void;
  }) => (
    <div
      data-testid="canvas"
      data-selected={selectedKey ?? ''}
      data-construction={constructionId ?? ''}
      data-all={String(allGroups !== null)}
      data-exploded={String(exploded)}
    >
      <button type="button" onClick={() => onSelectConstruction('w2')}>
        щелчок по стене
      </button>
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

const wall = { id: 'w1', kind: 'masonry' as const, shell: [[0, 0], [1000, 0], [1000, 200], [0, 200]] };

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
  walls: [wall, { ...wall, id: 'w2', kind: 'monolith_wall' }],
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

const NOTHING: IBuildingViewerSelection = { group: null, floor: null, detail: false, construction: null };

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
    expect(change).toHaveBeenCalledWith({
      ...NOTHING,
      floor: floorKey({ job_id: 'j2', page_index: 0, view: 0 }),
    });
  });

  it('панель этажа: типовая толщина плиты не «0», счёт конструкций по видам', async () => {
    mount({ ...NOTHING, floor: 'j1:0:0' });
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
    expect(change).toHaveBeenCalledWith({ ...NOTHING, floor: 'j1:0:0', detail: true });
  });

  it('детальный вид: этаж только для чтения, «К зданию» снимает режим', async () => {
    const change = mount({ ...NOTHING, floor: 'j1:0:0', detail: true });
    expect(await screen.findByTestId('floor3d')).toHaveAttribute('data-readonly', 'true');
    expect(screen.queryByRole('button', { name: 'Разнести этажи' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /К зданию/ }));
    expect(change).toHaveBeenCalledWith({ ...NOTHING, floor: 'j1:0:0', detail: false });
  });

  it('одно здание - в переключателе нет «Весь объект»', async () => {
    mount(NOTHING);
    await screen.findByTestId('canvas');
    expect(screen.queryByRole('option', { name: 'Весь объект' })).toBeNull();
  });

  it('щелчок по стене выбранного этажа уходит в адрес как конструкция', async () => {
    const change = mount({ ...NOTHING, floor: 'j1:0:0' });
    fireEvent.click(await screen.findByRole('button', { name: 'щелчок по стене' }));
    expect(change).toHaveBeenCalledWith({ ...NOTHING, floor: 'j1:0:0', construction: 'w2' });
  });

  it('Esc: сначала снимает конструкцию, вторым нажатием - этаж', async () => {
    const change = mount({ ...NOTHING, floor: 'j1:0:0', construction: 'w2' });
    await screen.findByTestId('canvas');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(change).toHaveBeenLastCalledWith({ ...NOTHING, floor: 'j1:0:0', construction: null });
  });

  it('Esc без выбранной конструкции снимает этаж', async () => {
    const change = mount({ ...NOTHING, floor: 'j1:0:0' });
    await screen.findByTestId('canvas');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(change).toHaveBeenLastCalledWith(NOTHING);
  });

  it('панель конструкции: параметры из расчёта листа и «Снять выбор»', async () => {
    vi.mocked(client.readCadConstructions).mockResolvedValue({
      data: {
        constructions: [
          {
            id: 'w2',
            kind: 'monolith_wall',
            thickness_nominal_mm: 200,
            thickness_measured_mm: 198,
            accepted: true,
            material: { value: null, source: null, evidence: [] },
            computed: {
              status: 'ok',
              warnings: [],
              sources: { height: null, thickness: null },
              thickness_mm: 200,
              length_m: 4.5,
              height_mm: 2800,
              wall_area_m2: 12.6,
              volume_m3: 2.52,
              area_m2: null,
            },
          },
        ],
        openings: [{ id: 'o1', kind: 'door', host_id: 'w2' }],
        totals: [],
        summary: { door_openings_without_host: 0, height_missing_count: 0, lintels_without_volume: 0, thickness_check_count: 0, unaccounted_gap_openings: 0 },
      },
    } as never);
    const change = mount({ ...NOTHING, floor: 'j1:0:0', construction: 'w2' });
    expect(await screen.findByRole('heading', { name: /Монолит — стена, 200 мм/ })).toBeInTheDocument();
    expect(screen.getByText('Двери в стене').nextSibling).toHaveTextContent('1');
    fireEvent.click(screen.getByRole('button', { name: 'Снять выбор' }));
    expect(change).toHaveBeenCalledWith({ ...NOTHING, floor: 'j1:0:0', construction: null });
  });

  it('конструкции нет в расчёте - пояснение вместо карточки', async () => {
    vi.mocked(client.readCadConstructions).mockResolvedValue({
      data: {
        constructions: [],
        openings: [],
        totals: [],
        summary: { door_openings_without_host: 0, height_missing_count: 0, lintels_without_volume: 0, thickness_check_count: 0, unaccounted_gap_openings: 0 },
      },
    } as never);
    mount({ ...NOTHING, floor: 'j1:0:0', construction: 'nope' });
    expect(await screen.findByText(/Конструкции нет в расчёте листа/)).toBeInTheDocument();
  });
});

describe('Просмотрщик объекта: весь объект', () => {
  beforeEach(() => {
    vi.mocked(client.readCadBuilding3D).mockResolvedValue({
      data: {
        floors: [
          floor(),
          floor({ job_id: 'k2', label: '1 этаж К2', group_key: 'k2', group_label: 'К2 · С1', corps: '2', section: '1' }),
        ],
        groups: [
          { key: 'k9s3', label: 'К9 · С3', floor_count: 1, aligned_count: 1 },
          { key: 'k2', label: 'К2 · С1', floor_count: 1, aligned_count: 1 },
        ],
        warnings: [],
      },
    } as never);
  });

  it('в переключателе есть «Весь объект»; выбор уходит в адрес и сбрасывает этаж', async () => {
    const change = mount({ ...NOTHING, floor: 'j1:0:0' });
    const select = await screen.findByLabelText('Корпус');
    expect(screen.getByRole('option', { name: 'Весь объект' })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: 'all' } });
    expect(change).toHaveBeenCalledWith({ group: 'all', floor: null, detail: false, construction: null });
  });

  it('режим «Весь объект»: холст получает группы, пометка про условное расположение, список по зданиям', async () => {
    mount({ ...NOTHING, group: 'all' });
    expect(await screen.findByText('Взаимное расположение корпусов условное')).toBeInTheDocument();
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-all', 'true');
    expect(screen.getByRole('list', { name: 'Этажи: К9 · С3' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Этажи: К2 · С1' })).toBeInTheDocument();
  });

  it('обычный режим: пометки нет, холст без групп', async () => {
    mount({ ...NOTHING, group: 'k2' });
    expect(await screen.findByTestId('canvas')).toHaveAttribute('data-all', 'false');
    expect(screen.queryByText('Взаимное расположение корпусов условное')).toBeNull();
  });

  it('выбор этажа в режиме сохраняет «all»', async () => {
    const change = mount({ ...NOTHING, group: 'all' });
    fireEvent.click(await screen.findByRole('button', { name: /1 этаж К2/ }));
    expect(change).toHaveBeenCalledWith(expect.objectContaining({ group: 'all', floor: 'k2:0:0' }));
  });
});

