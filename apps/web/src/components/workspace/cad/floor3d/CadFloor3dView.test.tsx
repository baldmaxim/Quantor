import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { floor3dFixture } from '@/lib/cad/floor3d-fixtures';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadFloor3dView } from './CadFloor3dView';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readCadFloor3D: vi.fn(),
  readCadConstructions: vi.fn(),
  readCadProjectLevels: vi.fn(),
  putCadFloor3dHole: vi.fn(),
  putCadSheetLevels: vi.fn(),
  putCadProjectLevels: vi.fn(),
}));

// Холст three.js в jsdom не нужен (нет WebGL): подставка отдаёт «щелчок по отверстию».
vi.mock('./CadFloor3dCanvas', () => ({
  CadFloor3dCanvas: ({
    onPick,
    measuring,
    selected,
  }: {
    onPick: (pick: unknown, anchor: unknown) => void;
    measuring: boolean;
    selected: { id: string } | null;
  }) => (
    <div data-testid="canvas" data-measuring={String(measuring)} data-selected={selected?.id ?? ''}>
      <button
        type="button"
        onClick={() => onPick({ kind: 'hole', category: 'hole', id: 'h1' }, { x: 20, y: 20 })}
      >
        щелчок по отверстию
      </button>
      <button type="button" onClick={() => onPick(null, { x: 1, y: 1 })}>
        щелчок в пустоту
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

const mount = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CadFloor3dView params={params} />
    </QueryClientProvider>,
  );
};

const ok = <T,>(data: T) => Promise.resolve({ data });

beforeEach(() => {
  vi.mocked(client.readCadConstructions).mockImplementation(
    () => ok({ constructions: [] }) as never,
  );
  vi.mocked(client.readCadProjectLevels).mockImplementation(() =>
    ok({ slab_thickness_mm: null, slab_source_ref: null, updated_at: null }) as never,
  );
});

describe('3D-вид этажа', () => {
  it('запрашивает модель того же задания, листа и вида, что у плана', async () => {
    vi.mocked(client.readCadFloor3D).mockImplementation(() => ok(floor3dFixture()) as never);
    mount();
    await screen.findByTestId('floor3d-heights');
    expect(client.readCadFloor3D).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { project_id: 'p1', job_id: 'j1', page_index: 2, view: 1 },
      }),
    );
  });

  it('конструкции не построены - подсказка, без ошибки', async () => {
    vi.mocked(client.readCadFloor3D).mockRejectedValue({ detail: { code: 'CAD_WALLS_NOT_READY' } });
    mount();
    expect(await screen.findByText(/Сначала постройте конструкции листа/)).toBeInTheDocument();
  });

  it('walls_outdated - просьба пересчитать конструкции', async () => {
    vi.mocked(client.readCadFloor3D).mockImplementation(() =>
      ok(
        floor3dFixture({
          slab: null,
          slab_holes: [],
          walls: [],
          lintels: [],
          bbox: null,
          warnings: [{ code: 'walls_outdated', message: 'Результат устарел. Пересчитайте конструкции.' }],
        }),
      ) as never,
    );
    mount();
    const alerts = await screen.findAllByText(/Пересчитайте конструкции/);
    expect(alerts.length).toBeGreaterThan(0);
  });

  it('предупреждения ответа - списком; стены без высоты отмечены', async () => {
    vi.mocked(client.readCadFloor3D).mockImplementation(() =>
      ok(floor3dFixture({ warnings: [{ code: 'x', message: 'Высота двери — допущение.' }] })) as never,
    );
    mount();
    expect(await screen.findByText('Высота двери — допущение.')).toBeInTheDocument();
    expect(screen.getByText(/Стены без высоты не построены: 1/)).toBeInTheDocument();
  });

  it('клик по отверстию: «Не отверстие» пишет решение и закрывает карточку', async () => {
    vi.mocked(client.readCadFloor3D).mockImplementation(() => ok(floor3dFixture()) as never);
    vi.mocked(client.putCadFloor3dHole).mockImplementation(
      () =>
        ok(
          floor3dFixture({
            slab_holes: floor3dFixture().slab_holes.map((hole) =>
              hole.key === 'h1' ? { ...hole, state: 'disabled' as const } : hole,
            ),
          }),
        ) as never,
    );
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'щелчок по отверстию' }));
    expect(screen.getByRole('dialog', { name: 'Отверстие плиты' })).toHaveTextContent('кандидат');
    fireEvent.click(screen.getByRole('button', { name: 'Не отверстие' }));
    await waitFor(() =>
      expect(client.putCadFloor3dHole).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { project_id: 'p1', job_id: 'j1', page_index: 2, view: 1, hole_key: 'h1' },
          body: { enabled: false },
        }),
      ),
    );
    await waitFor(() => expect(screen.queryByTestId('floor3d-popover')).toBeNull());
  });

  it('список отверстий: по убыванию площади, счётчики, PUT с нужным enabled', async () => {
    const base = floor3dFixture();
    vi.mocked(client.readCadFloor3D).mockImplementation(
      () =>
        ok(
          floor3dFixture({
            slab_holes: [
              { ...base.slab_holes[0]!, key: 'h1', area_m2: 1 },
              { ...base.slab_holes[1]!, key: 'h2', area_m2: 5 },
              { ...base.slab_holes[2]!, key: 'h3', area_m2: 3 },
            ],
          }),
        ) as never,
    );
    vi.mocked(client.putCadFloor3dHole).mockImplementation(() => ok(floor3dFixture()) as never);
    mount();
    const toggle = await screen.findByRole('button', { name: /Отверстия плиты \(3\)/ });
    expect(toggle).toHaveTextContent('отверстий 1, не отверстий 1');
    fireEvent.click(toggle);
    const rows = screen.getAllByTestId(/^floor3d-hole-/).map((row) => row.getAttribute('data-testid'));
    expect(rows).toEqual(['floor3d-hole-h2', 'floor3d-hole-h3', 'floor3d-hole-h1']);

    fireEvent.click(within(screen.getByTestId('floor3d-hole-h3')).getByRole('button', { name: 'Отверстие' }));
    await waitFor(() =>
      expect(client.putCadFloor3dHole).toHaveBeenLastCalledWith(
        expect.objectContaining({
          path: expect.objectContaining({ hole_key: 'h3' }),
          body: { enabled: true },
        }),
      ),
    );
    fireEvent.click(within(screen.getByTestId('floor3d-hole-h2')).getByRole('button', { name: 'Не отверстие' }));
    await waitFor(() =>
      expect(client.putCadFloor3dHole).toHaveBeenLastCalledWith(
        expect.objectContaining({
          path: expect.objectContaining({ hole_key: 'h2' }),
          body: { enabled: false },
        }),
      ),
    );
  });

  it('выделение: клик ставит, клик в пустоту, Esc и закрытие плашки снимают', async () => {
    vi.mocked(client.readCadFloor3D).mockImplementation(() => ok(floor3dFixture()) as never);
    mount();
    const canvas = await screen.findByTestId('canvas');
    fireEvent.click(screen.getByRole('button', { name: 'щелчок по отверстию' }));
    expect(canvas).toHaveAttribute('data-selected', 'h1');
    fireEvent.click(screen.getByRole('button', { name: 'щелчок в пустоту' }));
    expect(canvas).toHaveAttribute('data-selected', '');
    fireEvent.click(screen.getByRole('button', { name: 'щелчок по отверстию' }));
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(canvas).toHaveAttribute('data-selected', '');
    fireEvent.click(screen.getByRole('button', { name: 'щелчок по отверстию' }));
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть карточку' }));
    expect(canvas).toHaveAttribute('data-selected', '');
  });

  it('«Измерить»: режим вкл/выкл, плашка в режиме не открывается, Esc выходит', async () => {
    vi.mocked(client.readCadFloor3D).mockImplementation(() => ok(floor3dFixture()) as never);
    mount();
    const canvas = await screen.findByTestId('canvas');
    const toggle = screen.getByRole('button', { name: 'Измерить' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(canvas).toHaveAttribute('data-measuring', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'щелчок по отверстию' }));
    expect(screen.queryByTestId('floor3d-popover')).toBeNull();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(canvas).toHaveAttribute('data-measuring', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'щелчок по отверстию' }));
    expect(screen.getByTestId('floor3d-popover')).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(canvas).toHaveAttribute('data-measuring', 'true');
    expect(screen.queryByTestId('floor3d-popover')).toBeNull();
    fireEvent.click(toggle);
    expect(canvas).toHaveAttribute('data-measuring', 'false');
  });

  it('заголовок 3D-вида - этаж по заголовку плана; без заголовка подписи нет', async () => {
    vi.mocked(client.readCadFloor3D).mockImplementation(
      () => ok(floor3dFixture({ title: { corps: '9', section: '3', floors: ['15'], text: null } })) as never,
    );
    mount();
    const heading = await screen.findByTestId('floor3d-title');
    expect(heading).toHaveTextContent('К9 · С3 · 15 эт.');
    expect(heading).toHaveAttribute('title', 'Корпус 9, секция 3, 15 этаж');
  });

  it('нет заголовка плана - подписи этажом нет', async () => {
    vi.mocked(client.readCadFloor3D).mockImplementation(() => ok(floor3dFixture()) as never);
    mount();
    await screen.findByTestId('floor3d-heights');
    expect(screen.queryByTestId('floor3d-title')).toBeNull();
  });
});
