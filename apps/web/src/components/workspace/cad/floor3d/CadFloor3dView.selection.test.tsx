import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { construction, constructionsRead } from '@/lib/cad/constructions-fixtures';
import { floor3dFixture } from '@/lib/cad/floor3d-fixtures';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadFloor3dView, type ICadFloor3dViewProps } from './CadFloor3dView';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readCadFloor3D: vi.fn(),
  readCadConstructions: vi.fn(),
  readCadProjectLevels: vi.fn(),
}));

// Холст three.js в jsdom не нужен: подставка отдаёт щелчки по стене, плите, перемычке и пустоте.
vi.mock('./CadFloor3dCanvas', () => ({
  CadFloor3dCanvas: ({
    onPick,
    selectedIds,
    selected,
    hiddenCategories,
  }: {
    onPick: (pick: unknown, anchor: unknown) => void;
    selectedIds: ReadonlySet<string>;
    selected: { id: string } | null;
    hiddenCategories?: ReadonlySet<string>;
  }) => (
    <div
      data-testid="canvas"
      data-ids={[...selectedIds].join(',')}
      data-local={selected?.id ?? ''}
      data-hidden={[...(hiddenCategories ?? [])].join(',')}
    >
      <button type="button" onClick={() => onPick({ kind: 'prism', category: 'masonry', id: 'w1' }, { x: 20, y: 20 })}>
        стена
      </button>
      <button type="button" onClick={() => onPick({ kind: 'prism', category: 'slab', id: 'slab' }, { x: 20, y: 20 })}>
        плита
      </button>
      <button type="button" onClick={() => onPick({ kind: 'prism', category: 'lintel', id: 'o1' }, { x: 20, y: 20 })}>
        перемычка
      </button>
      <button
        type="button"
        onClick={() => onPick({ kind: 'prism', category: 'frame_partition', id: 'w3' }, { x: 20, y: 20 })}
      >
        перегородка
      </button>
      <button type="button" onClick={() => onPick(null, { x: 1, y: 1 })}>
        пустота
      </button>
    </div>
  ),
}));

const params: ICadViewParams = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'j1',
  attempt: 1,
  pageIndex: 2,
  view: 1,
};

const mount = (props: Partial<ICadFloor3dViewProps> = {}) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CadFloor3dView params={params} {...props} />
    </QueryClientProvider>,
  );
};

// Первый рендер файла платит за холодный импорт модулей: ждём дольше стандартной секунды.
const button = (name: string) => screen.findByRole('button', { name }, { timeout: 5000 });

const ok = <T,>(data: T) => Promise.resolve({ data });

beforeEach(() => {
  vi.mocked(client.readCadFloor3D).mockImplementation(() => ok(floor3dFixture()) as never);
  vi.mocked(client.readCadProjectLevels).mockImplementation(() =>
    ok({ slab_thickness_mm: null, slab_source_ref: null, updated_at: null }) as never,
  );
  vi.mocked(client.readCadConstructions).mockImplementation(() => ok({ constructions: [] }) as never);
});

describe('3D-вид: общий выбор конструкций', () => {
  it('клик по плите выделяет её id slab и открывает плашку; плиты нет среди конструкций - «Плита не посчитана»', async () => {
    const onSelect = vi.fn();
    mount({ onSelectConstruction: onSelect, selectedIds: new Set(['slab']) });
    fireEvent.click(await button('плита'));
    expect(onSelect).toHaveBeenCalledWith('slab');
    const dialog = await screen.findByRole('dialog', { name: 'Плита перекрытия' });
    expect(dialog).toHaveTextContent('Плита не посчитана');
    expect(dialog).not.toHaveTextContent('0');
  });

  it('плашка плиты: площадь, толщина и объём из конструкции slab', async () => {
    const slab = construction({ id: 'slab', kind: 'floor_slab' });
    vi.mocked(client.readCadConstructions).mockImplementation(
      () =>
        ok({
          ...constructionsRead(),
          constructions: [
            {
              ...slab,
              computed: { ...slab.computed, area_m2: 58.5, thickness_mm: 200, volume_m3: 11.7 },
            },
          ],
        }) as never,
    );
    mount({ onSelectConstruction: vi.fn(), selectedIds: new Set(['slab']) });
    fireEvent.click(await button('плита'));
    const dialog = await screen.findByRole('dialog', { name: 'Плита перекрытия' });
    await vi.waitFor(() => expect(dialog).toHaveTextContent('58,5 м²'));
    expect(dialog).toHaveTextContent('200 мм');
    expect(dialog).toHaveTextContent('11,7 м³');
  });

  it('клик по стене - выбор {id}, без локальной подсветки; в пустоту - сброс', async () => {
    const onSelect = vi.fn();
    mount({ onSelectConstruction: onSelect, selectedIds: new Set(['w1']) });
    fireEvent.click(await button('стена'));
    expect(onSelect).toHaveBeenLastCalledWith('w1');
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-local', '');
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-ids', 'w1');
    fireEvent.click(screen.getByRole('button', { name: 'пустота' }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('Esc и закрытие плашки очищают общий выбор', async () => {
    const onSelect = vi.fn();
    mount({ onSelectConstruction: onSelect, selectedIds: new Set(['w1']) });
    fireEvent.click(await button('стена'));
    onSelect.mockClear();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onSelect).toHaveBeenCalledWith(null);
    onSelect.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'стена' }));
    onSelect.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть карточку' }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it('клик по перегородке - выбор {id} как у стены, плашка с площадью без объёма', async () => {
    const wall = floor3dFixture().walls[0]!;
    vi.mocked(client.readCadFloor3D).mockImplementation(
      () =>
        ok(
          floor3dFixture({
            walls: [{ ...wall, construction_key: 'w3', kind: 'frame_partition', family: 'frame_partition' }],
          }),
        ) as never,
    );
    const partition = construction({ id: 'w3', kind: 'frame_partition' });
    vi.mocked(client.readCadConstructions).mockImplementation(
      () =>
        ok({
          ...constructionsRead(),
          constructions: [
            { ...partition, computed: { ...partition.computed, wall_area_m2: 13.5, volume_m3: null } },
          ],
        }) as never,
    );
    const onSelect = vi.fn();
    mount({ onSelectConstruction: onSelect, selectedIds: new Set(['w3']) });
    fireEvent.click(await button('перегородка'));
    expect(onSelect).toHaveBeenLastCalledWith('w3');
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-local', '');
    const dialog = await screen.findByRole('dialog', { name: 'Каркасная перегородка ГКЛ' });
    await vi.waitFor(() => expect(dialog).toHaveTextContent('13,5 м²'));
    expect(dialog).not.toHaveTextContent('Объём');
  });

  it('перемычка: «Выбрать стену» выбирает владельца и переключает плашку на него', async () => {
    const lintel = floor3dFixture().lintels[0]!;
    vi.mocked(client.readCadFloor3D).mockImplementation(
      () => ok(floor3dFixture({ lintels: [{ ...lintel, host_id: 'w1' }] })) as never,
    );
    vi.mocked(client.readCadConstructions).mockImplementation(
      () => ok({ ...constructionsRead(), constructions: [construction({ id: 'w1' })] }) as never,
    );
    const onSelect = vi.fn();
    mount({ onSelectConstruction: onSelect, selectedIds: new Set(['w1']) });
    fireEvent.click(await button('перемычка'));
    const lintelDialog = await screen.findByRole('dialog', { name: 'Перемычка над дверью' });
    await vi.waitFor(() => expect(lintelDialog).toHaveTextContent('Стена: Кладка, 120 мм'));
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Выбрать стену' }));
    expect(onSelect).toHaveBeenCalledWith('w1');
    expect(await screen.findByRole('dialog', { name: 'Кладка' })).toBeInTheDocument();
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-local', '');
  });

  it('перемычка выделяется только локально: общий выбор не меняется', async () => {
    const onSelect = vi.fn();
    mount({ onSelectConstruction: onSelect, selectedIds: new Set(['w1']) });
    fireEvent.click(await button('перемычка'));
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-local', 'o1');
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-ids', 'w1');
  });

  it('скрытые категории и общий выбор доходят до холста', async () => {
    mount({ selectedIds: new Set(['w1', 'slab']), hiddenCategories: new Set(['masonry']) });
    const canvas = await screen.findByTestId('canvas', {}, { timeout: 5000 });
    expect(canvas).toHaveAttribute('data-ids', 'w1,slab');
    expect(canvas).toHaveAttribute('data-hidden', 'masonry');
  });
});
