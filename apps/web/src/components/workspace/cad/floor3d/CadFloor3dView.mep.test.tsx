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
  readCadEomJob: vi.fn(),
  readCadEomRoutes3D: vi.fn(),
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
    routes: { elements?: readonly unknown[] } | null;
  }) => (
    <div
      data-testid="canvas"
      data-routes={routes === null ? '' : 'yes'}
      data-elements={routes?.elements?.length ?? 0} data-mep={selectedMep === null ? '' : `${selectedMep.kind}:${selectedMep.index}`}>
      <button type="button" onClick={() => onPickMep({ kind: 'route', index: 0 }, { x: 20, y: 20 })}>
        трасса
      </button>
      <button type="button" onClick={() => onPickMep({ kind: 'element', index: 0 }, { x: 20, y: 20 })}>
        прибор
      </button>
      <button type="button" onClick={() => onPickMep({ kind: 'route', index: 1 }, { x: 20, y: 20 })}>
        линия ЭОМ
      </button>
      <button type="button" onClick={() => onPickMep({ kind: 'element', index: 1 }, { x: 20, y: 20 })}>
        прибор ЭОМ
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

// ЭОМ и СС листа: в сцене идут после механики, индекс выбора - в общем списке.
const eomJob: client.CadEomJobRead = {
  job_id: 'e1',
  status: 'succeeded',
  stage: null,
  progress: 1,
  error_code: null,
  error_message: null,
  generator_version: 'cad_eom.v0.1',
  created_at: '2026-11-14T10:00:00Z',
  finished_at: '2026-11-14T10:01:00Z',
};

const eom3d: client.CadEomRoutes3dOut = {
  job_id: 'e1',
  generator_version: 'cad_eom.v0.1',
  floor_elevation_mm: 3000,
  floor_height_mm: 2800,
  levels_elevation_mm: 3000,
  levels_height_mm: 2800,
  heights_match: true,
  polylines: [
    {
      layer: 'E-EO-LT',
      pts: [[0, 0, 2600], [2000, 0, 2600]],
      shape: 'round',
      dn_mm: 16,
      item: 'Кабель ВВГнг(А)-LS 3×1,5 в трубе Ø16',
      apt: 'Кв 1',
    },
  ],
  elements: [
    {
      type: 'device',
      subtype: 'panel_shell',
      layer: 'E-EO-DEV',
      pos: [0, 80, 1900],
      axis: [0, 1000, 0],
      w_mm: 300,
      h_mm: 400,
      d_mm: 120,
      name: 'ЩМк',
      apt: 'Кв 1',
    },
  ],
  quantities: [],
  apartments: 1,
  issues: [],
};

const mount = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      {/* Рабочая область: 3D рисует route-задание плана (`j2`). */}
      <CadFloor3dView params={params} routeJobId="j2" onSelectConstruction={vi.fn()} />
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
  vi.mocked(client.readCadEomJob).mockImplementation(
    () => Promise.reject({ detail: { code: 'CAD_EOM_NOT_FOUND' } }) as never,
  );
  vi.mocked(client.readCadEomRoutes3D).mockImplementation(() => ok(eom3d) as never);
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

  it('ЭОМ и СС вместе с механикой: прибор и линия - по названию генератора, с размерами', async () => {
    vi.mocked(client.readCadEomJob).mockImplementation(() => ok(eomJob) as never);
    mount();
    const device = await button('прибор ЭОМ');
    // Прибор механики и прибор ЭОМ - один список сцены: ЭОМ вторым.
    await waitFor(() => expect(canvas()).toHaveAttribute('data-elements', '2'), { timeout: 4000 });
    fireEvent.click(device);
    const panel = await screen.findByRole('dialog', { name: 'ЩМк' });
    expect(panel).toHaveTextContent('Щиты и приборы ЭОМ');
    expect(panel).toHaveTextContent('300×400×120 мм');
    expect(canvas()).toHaveAttribute('data-mep', 'element:1');
    fireEvent.click(screen.getByRole('button', { name: 'линия ЭОМ' }));
    const line = await screen.findByRole('dialog', { name: 'Кабель ВВГнг(А)-LS 3×1,5 в трубе Ø16' });
    expect(line).toHaveTextContent('Временное освещение квартир');
    expect(line).toHaveTextContent('Ø 16 мм');
    expect(line).not.toHaveTextContent('Изоляция');
  });

  it('клик по конструкции снимает выбор ВИС', async () => {
    mount();
    fireEvent.click(await button('трасса'));
    fireEvent.click(screen.getByRole('button', { name: 'стена' }));
    await waitFor(() => expect(canvas()).toHaveAttribute('data-mep', ''));
  });
});
