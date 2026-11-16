import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
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
    allGroups,
    exploded,
    onSelect,
    onOpenDetail,
  }: {
    selectedKey: string | null;
    allGroups: unknown[] | null;
    exploded: boolean;
    onSelect: (key: string | null) => void;
    onOpenDetail: (key: string) => void;
  }) => (
    <div
      data-testid="canvas"
      data-selected={selectedKey ?? ''}
      data-all={String(allGroups !== null)}
      data-exploded={String(exploded)}
    >
      <button type="button" onClick={() => onSelect(null)}>
        снять выбор этажа
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

const NOTHING: IBuildingViewerSelection = { group: null, floor: null, detail: false };

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

  it('панель копии типового листа: пометка, качество совмещения, высота по стопке, без итогов листа', async () => {
    vi.mocked(client.readCadBuilding3D).mockResolvedValue({
      data: {
        floors: [
          floor({ label: 'К9 · С3 · 5 эт. (по листу «5, 7 эт.»)' }),
          floor({
            label: 'К9 · С3 · 7 эт. (по листу «5, 7 эт.»)',
            base_z_mm: 6600,
            typical_of: 'К9 · С3 · 5, 7 эт.',
            alignment: 'axes',
            alignment_axes: ['3.1', '3.2', 'А'],
            alignment_rms_mm: 2.1,
            alignment_max_mm: 6,
            alignment_axes_common: 4,
            alignment_scale_permille: 0.4,
            floor_height_known: false,
            floor_height_source: 'derived_stack',
            floor_height_mm: 3300,
          }),
          floor({ job_id: 'j2', label: '8 эт.', base_z_mm: 9900 }),
        ],
        groups: [{ key: 'k9s3', label: 'К9 · С3', floor_count: 3 }],
        warnings: [],
      },
    } as never);
    mount({ ...NOTHING, floor: 'j1:0:0@6600' });
    expect(await screen.findByText(/Этаж показан по типовому листу «К9 · С3 · 5, 7 эт.»/)).toBeInTheDocument();
    expect(screen.getByText('Качество совмещения').nextSibling).toHaveTextContent(
      'остаток 2,1 мм (до 6,0), согласных осей 3 из 4, наклон шкалы 0,40 ‰',
    );
    expect(screen.getByText('Высота этажа').nextSibling).toHaveTextContent(
      'не определена, показана по отметке следующего этажа (3,3 м)',
    );
    // Объёмы листа у копии не показываются: она в них не входит.
    expect(screen.queryByText('Конструкции листа ещё не посчитаны.')).toBeNull();
    // В списке у копии светофор: три оси - жёлтый.
    expect(screen.getByRole('img', { name: 'совмещение приблизительное' })).toBeInTheDocument();
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

  it('холст снял выбор (повторный щелчок по этажу или в пустоту) - этаж уходит из адреса', async () => {
    const change = mount({ ...NOTHING, floor: 'j1:0:0' });
    fireEvent.click(await screen.findByRole('button', { name: 'снять выбор этажа' }));
    expect(change).toHaveBeenCalledWith(NOTHING);
  });

  it('Esc снимает выбор этажа', async () => {
    const change = mount({ ...NOTHING, floor: 'j1:0:0' });
    await screen.findByTestId('canvas');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(change).toHaveBeenLastCalledWith(NOTHING);
  });

  it('Esc снимает выбор, даже когда фокус остался на переключателе корпуса', async () => {
    vi.mocked(client.readCadBuilding3D).mockResolvedValue({
      data: {
        floors: [floor(), floor({ job_id: 'k2', group_key: 'k2', group_label: 'К2 · С1' })],
        groups: [
          { key: 'k9s3', label: 'К9 · С3', floor_count: 1 },
          { key: 'k2', label: 'К2 · С1', floor_count: 1 },
        ],
        warnings: [],
      },
    } as never);
    const change = mount({ ...NOTHING, group: 'all', floor: 'j1:0:0' });
    const select = await screen.findByLabelText('Корпус');
    select.focus();
    fireEvent.keyDown(select, { key: 'Escape' });
    expect(change).toHaveBeenLastCalledWith({ ...NOTHING, group: 'all' });
  });

  it('на общем виде нет выбора конструкций: панели конструкции нет', async () => {
    mount({ ...NOTHING, floor: 'j1:0:0' });
    await screen.findByTestId('canvas');
    expect(screen.queryByRole('button', { name: 'Снять выбор' })).toBeNull();
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
          { key: 'k9s3', label: 'К9 · С3', floor_count: 1, aligned_count: 1, placement: 'reference' },
          {
            key: 'k2',
            label: 'К2 · С1',
            floor_count: 1,
            aligned_count: 1,
            placement: 'none',
            placement_message: 'нет общих осей с поставленными зданиями',
          },
        ],
        warnings: [{ code: 'floor_missing', message: 'АР · лист 4 «План 4 этажа»: плана этажа нет в 3D.' }],
        service_sheets: [
          {
            job_id: 's1',
            revision_id: 'r1',
            document_id: 'd1',
            page_index: 143,
            view: 1,
            label: 'АР · лист 144',
            reason: 'not_plan',
            message: 'АР · лист 144: не план этажа: по паспорту листа - разрез.',
          },
        ],
      },
    } as never);
  });

  it('по умолчанию открыт весь объект, в том числе по ссылке на этаж и с устаревшим корпусом', async () => {
    for (const selection of [NOTHING, { ...NOTHING, floor: 'j1:0:0' }, { ...NOTHING, group: 'gone' }]) {
      const view = mount(selection);
      expect(await screen.findByTestId('canvas')).toHaveAttribute('data-all', 'true');
      expect(screen.getByLabelText('Корпус')).toHaveValue('all');
      expect(view).not.toHaveBeenCalled();
      cleanup();
    }
  });

  it('в переключателе есть «Весь объект»; выбор корпуса уходит в адрес и сбрасывает этаж', async () => {
    const change = mount({ ...NOTHING, floor: 'j1:0:0' });
    const select = await screen.findByLabelText('Корпус');
    expect(screen.getByRole('option', { name: 'Весь объект' })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: 'k2' } });
    expect(change).toHaveBeenCalledWith({ group: 'k2', floor: null, detail: false });
  });

  it('режим «Весь объект»: холст получает группы, не поставленный корпус назван с причиной', async () => {
    mount({ ...NOTHING, group: 'all' });
    expect(await screen.findByText(/Полупрозрачные корпуса не поставлены на объект/)).toBeInTheDocument();
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-all', 'true');
    expect(screen.getByRole('list', { name: 'Этажи: К9 · С3' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Этажи: К2 · С1' })).toBeInTheDocument();
    const lost = screen.getByRole('region', { name: 'К2 · С1' });
    expect(lost).toHaveTextContent('Не поставлен на объект: нет общих осей с поставленными зданиями');
    expect(screen.getByRole('region', { name: 'К9 · С3' })).not.toHaveTextContent('Не поставлен');
  });

  it('обычный режим: пометки нет, холст без групп', async () => {
    mount({ ...NOTHING, group: 'k2' });
    expect(await screen.findByTestId('canvas')).toHaveAttribute('data-all', 'false');
    expect(screen.queryByText(/Полупрозрачные корпуса/)).toBeNull();
  });

  it('замечания сборки: чего нет в 3D и служебные листы', async () => {
    mount({ ...NOTHING, group: 'all' });
    expect(await screen.findByText('Замечания сборки: 1, служебных листов: 1')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Замечания сборки' })).toHaveTextContent('плана этажа нет в 3D');
    expect(screen.getByRole('list', { name: 'Служебные листы' })).toHaveTextContent('по паспорту листа - разрез');
  });

  it('выбор этажа в режиме сохраняет «all»', async () => {
    const change = mount({ ...NOTHING, group: 'all' });
    fireEvent.click(await screen.findByRole('button', { name: /1 этаж К2/ }));
    expect(change).toHaveBeenCalledWith(expect.objectContaining({ group: 'all', floor: 'k2:0:0' }));
  });
});

