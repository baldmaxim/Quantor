import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { floor3dFixture } from '@/lib/cad/floor3d-fixtures';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadFloor3dView } from './CadFloor3dView';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readCadFloor3D: vi.fn(),
  readCadConstructions: vi.fn(),
  readCadProjectLevels: vi.fn(),
  readCadMepRoutes3D: vi.fn(),
  listCadJobs: vi.fn(),
}));

// Холст three.js в jsdom не нужен: подставка отдаёт щелчки по трассе, прибору, стене и пустоте.
vi.mock('./CadFloor3dCanvas', () => ({
  CadFloor3dCanvas: ({
    onPick,
    onPickMep,
    onMove,
    selectedMep,
    routes,
  }: {
    onPick: (pick: unknown, anchor: unknown) => void;
    onPickMep: (pick: { kind: string; index: number }, anchor: unknown) => void;
    onMove: () => void;
    selectedMep: { kind: string; index: number } | null;
    routes: unknown;
  }) => (
    <div data-testid="canvas" data-routes={routes === null ? '' : 'yes'} data-mep={selectedMep === null ? '' : `${selectedMep.kind}:${selectedMep.index}`}>
      <button type="button" onClick={() => onPickMep({ kind: 'route', index: 0 }, { x: 20, y: 20 })}>
        трасса
      </button>
      <button type="button" onClick={() => onPickMep({ kind: 'element', index: 0 }, { x: 20, y: 20 })}>
        прибор
      </button>
      <button type="button" onClick={() => onPick({ kind: 'prism', category: 'masonry', id: 'w1' }, { x: 20, y: 20 })}>
        стена
      </button>
      <button type="button" onClick={() => onPick(null, { x: 1, y: 1 })}>
        пустота
      </button>
      <button type="button" onClick={onMove}>
        камера
      </button>
    </div>
  ),
}));

const params: ICadViewParams = { projectId: 'p1', revisionId: 'r1', jobId: 'j1', attempt: 1, pageIndex: 2, view: 1 };

const ok = <T,>(data: T) => Promise.resolve({ data });

const routes3d: client.CadMepRoutes3dOut = {
  job_id: 'j2',
  generator_version: 'cad_mep.v15',
  floor_elevation_mm: 3000,
  floor_height_mm: 2800,
  levels_elevation_mm: 3000,
  levels_height_mm: 2800,
  heights_match: true,
  polylines: [
    {
      layer: 'M-VK-K1',
      pts: [[0, 0, 0], [0, 0, 2000]],
      kind: 'riser',
      shape: 'round',
      dn_mm: 110,
      dn_source: 'registry',
      mark: 'Ст К1-3',
      insulation_mm: 0,
    },
  ],
  elements: [
    {
      type: 'terminal',
      subtype: 'wc',
      layer: 'M-SAN-WC',
      pos: [100, 100, 400],
      axis: [0, 0, 1000],
      w_mm: 360,
      length_mm: 600,
      h_mm: 800,
      mark: 'У-1',
    },
  ],
};

const mount = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CadFloor3dView params={params} onSelectConstruction={vi.fn()} />
    </QueryClientProvider>,
  );
};

// Трассы читаются после модели: щелчки по ВИС возможны, когда они дошли до холста.
const button = async (name: string) => {
  const found = await screen.findByRole('button', { name }, { timeout: 5000 });
  await waitFor(() => expect(screen.getByTestId('canvas')).toHaveAttribute('data-routes', 'yes'));
  return found;
};
const canvas = () => screen.getByTestId('canvas');

beforeEach(() => {
  vi.mocked(client.readCadFloor3D).mockImplementation(() => ok(floor3dFixture()) as never);
  vi.mocked(client.readCadProjectLevels).mockImplementation(() =>
    ok({ slab_thickness_mm: null, slab_source_ref: null, updated_at: null }) as never,
  );
  vi.mocked(client.readCadConstructions).mockImplementation(() => ok({ constructions: [] }) as never);
  vi.mocked(client.listCadJobs).mockImplementation(() => ok({ items: [] }) as never);
  vi.mocked(client.readCadMepRoutes3D).mockImplementation(() => ok(routes3d) as never);
});

describe('3D-вид: выбор трасс и элементов ВИС', () => {
  it('клик по трассе выделяет её и открывает плашку; повторный клик снимает выбор', async () => {
    mount();
    fireEvent.click(await button('трасса'));
    const dialog = await screen.findByRole('dialog', { name: 'Стояк' });
    expect(dialog).toHaveTextContent('Канализация К1');
    expect(dialog).toHaveTextContent('Ст К1-3');
    expect(dialog).toHaveTextContent('Ø 110 мм');
    expect(dialog).toHaveTextContent('по реестру');
    expect(canvas()).toHaveAttribute('data-mep', 'route:0');
    fireEvent.click(screen.getByRole('button', { name: 'трасса' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(canvas()).toHaveAttribute('data-mep', '');
  });

  it('движение камеры закрывает плашку, выбор остаётся; повторный клик после этого снимает выбор', async () => {
    mount();
    fireEvent.click(await button('трасса'));
    await screen.findByRole('dialog', { name: 'Стояк' });
    fireEvent.click(screen.getByRole('button', { name: 'камера' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(canvas()).toHaveAttribute('data-mep', 'route:0');
    fireEvent.click(screen.getByRole('button', { name: 'трасса' }));
    expect(canvas()).toHaveAttribute('data-mep', '');
  });

  it('прибор: название по-русски, размеры корпуса, марка', async () => {
    mount();
    fireEvent.click(await button('прибор'));
    const dialog = await screen.findByRole('dialog', { name: 'Унитаз' });
    expect(dialog).toHaveTextContent('360×600×800 мм');
    expect(dialog).toHaveTextContent('У-1');
    expect(canvas()).toHaveAttribute('data-mep', 'element:0');
  });

  it('другой элемент заменяет выбор; клик в пустоту и Esc снимают', async () => {
    mount();
    fireEvent.click(await button('трасса'));
    fireEvent.click(screen.getByRole('button', { name: 'прибор' }));
    expect(canvas()).toHaveAttribute('data-mep', 'element:0');
    fireEvent.click(screen.getByRole('button', { name: 'пустота' }));
    expect(canvas()).toHaveAttribute('data-mep', '');
    fireEvent.click(screen.getByRole('button', { name: 'трасса' }));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(canvas()).toHaveAttribute('data-mep', '');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('клик по конструкции снимает выбор ВИС', async () => {
    mount();
    fireEvent.click(await button('трасса'));
    fireEvent.click(screen.getByRole('button', { name: 'стена' }));
    await waitFor(() => expect(canvas()).toHaveAttribute('data-mep', ''));
  });
});
