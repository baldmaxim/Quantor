import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { floor3dFixture } from '@/lib/cad/floor3d-fixtures';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import { layer } from '@/lib/tender/fixtures';

import { CadFloor3dView } from './CadFloor3dView';

const flags = vi.hoisted(() => ({
  engine: true,
  layers: undefined as { layers: unknown[] } | undefined,
}));

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

vi.mock('@/lib/tender/layers', () => ({
  useMepEngineEnabled: () => flags.engine,
  useTenderExchangeEnabled: () => flags.layers !== undefined,
  useTenderViewLayers: () => ({ data: flags.layers }),
}));

// Холст three.js в jsdom не нужен: подставка отдаёт слои и скрытые имена, щелчок по ВИС.
vi.mock('./CadFloor3dCanvas', () => ({
  CadFloor3dCanvas: ({
    onPickMep,
    routes,
    hiddenLayerNames,
  }: {
    onPickMep: (pick: { kind: string; index: number }, anchor: unknown) => void;
    routes: { polylines: { layer: string }[]; layerTokens?: Record<string, string> } | null;
    hiddenLayerNames?: ReadonlySet<string>;
  }) => (
    <div
      data-testid="canvas"
      data-layers={routes?.polylines.map((line) => line.layer).join(',') ?? ''}
      data-tokens={Object.values(routes?.layerTokens ?? {}).join(',')}
      data-hidden={[...(hiddenLayerNames ?? [])].join(',')}
    >
      <button type="button" onClick={() => onPickMep({ kind: 'route', index: 0 }, { x: 20, y: 20 })}>
        первая трасса
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

const ok = <T,>(data: T) => Promise.resolve({ data });

const routes3d = {
  job_id: 'j2',
  generator_version: 'cad_mep.v7',
  floor_elevation_mm: 3000,
  floor_height_mm: 2800,
  levels_elevation_mm: 3000,
  levels_height_mm: 2800,
  heights_match: true,
  polylines: [{ layer: 'M-OV-T1', pts: [[0, 0, 100], [1000, 0, 100]] }],
} as unknown as client.CadMepRoutes3dOut;

const mount = (hidden?: ReadonlySet<string>) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CadFloor3dView params={params} routeJobId="j2" hiddenLayerNames={hidden} />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  flags.engine = true;
  flags.layers = undefined;
  window.localStorage.clear();
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
  vi.mocked(client.readCadEomRoutes3D).mockImplementation(
    () => Promise.reject({ detail: { code: 'CAD_EOM_NOT_FOUND' } }) as never,
  );
  vi.mocked(client.readCadMepRoutes3D).mockClear();
});

describe('3D этажа: расчёты TENDER и трассы движка', () => {
  it('расчёт ложится в те же трассы сцены слоем tender:<calc_id> с токеном цвета системы', async () => {
    flags.layers = { layers: [layer()] };
    mount();
    await waitFor(() =>
      expect(screen.getByTestId('canvas')).toHaveAttribute('data-layers', 'M-OV-T1,tender:c1'),
    );
    expect(screen.getByTestId('canvas')).toHaveAttribute('data-tokens', '--tender-sys-heating');
  });

  it('клик по объекту расчёта открывает ту же плашку, что на плане: версия, система, примечание', async () => {
    flags.engine = false;
    flags.layers = { layers: [layer()] };
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'первая трасса' }));
    const dialog = await screen.findByRole('dialog', { name: 'Трасса' });
    expect(dialog).toHaveTextContent('Отопление жилой части');
    expect(dialog).toHaveTextContent('№3 v3');
    expect(dialog).toHaveTextContent('T1-a');
  });

  it('скрытые расчёты передаются холсту: имена из общего хранилища слоёв', async () => {
    flags.layers = { layers: [layer()] };
    mount(new Set(['tender:c1']));
    await waitFor(() =>
      expect(screen.getByTestId('canvas')).toHaveAttribute('data-hidden', 'tender:c1'),
    );
  });

  it('cad.mep_engine выключен: трассы движка не читаются и не рисуются, расчёт остаётся', async () => {
    flags.engine = false;
    flags.layers = { layers: [layer()] };
    mount();
    await waitFor(() =>
      expect(screen.getByTestId('canvas')).toHaveAttribute('data-layers', 'tender:c1'),
    );
    expect(client.readCadMepRoutes3D).not.toHaveBeenCalled();
    expect(client.readCadEomRoutes3D).not.toHaveBeenCalled();
  });

  it('ни трасс, ни расчётов - трасс на холсте нет', async () => {
    flags.engine = false;
    mount();
    await waitFor(() => expect(screen.getByTestId('canvas')).toHaveAttribute('data-layers', ''));
  });
});
