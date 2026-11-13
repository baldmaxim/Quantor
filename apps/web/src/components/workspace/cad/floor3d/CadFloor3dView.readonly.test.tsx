import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
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

vi.mock('./CadFloor3dCanvas', () => ({
  CadFloor3dCanvas: ({ onPick }: { onPick: (pick: unknown, anchor: unknown) => void }) => (
    <button
      type="button"
      onClick={() => onPick({ kind: 'hole', category: 'hole', id: 'h1' }, { x: 20, y: 20 })}
    >
      щелчок по отверстию
    </button>
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

const mount = (readOnly: boolean) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <CadFloor3dView params={params} readOnly={readOnly} />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  vi.mocked(client.listCadJobs).mockImplementation(() => ok({ items: [] }) as never);
  vi.mocked(client.readCadMepRoutes3D).mockImplementation(
    () => Promise.reject({ detail: { code: 'CAD_ROUTES_NOT_FOUND' } }) as never,
  );
  vi.mocked(client.readCadConstructions).mockImplementation(() => ok({ constructions: [] }) as never);
  vi.mocked(client.readCadProjectLevels).mockImplementation(() =>
    ok({ slab_thickness_mm: null, slab_source_ref: null, updated_at: null }) as never,
  );
  vi.mocked(client.readCadFloor3D).mockImplementation(
    () => ok(floor3dFixture({ warnings: [{ code: 'x', message: 'Высота двери — допущение.' }] })) as never,
  );
});

describe('3D-вид этажа: только просмотр', () => {
  it('нет выгрузки DXF, высот и списка отверстий; предупреждения и «Измерить» остаются', async () => {
    mount(true);
    // Модель прочитана: в панели просмотра есть кнопка предупреждений.
    expect(await screen.findByRole('button', { name: 'Предупреждения модели этажа' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Скачать 3D DXF' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Высоты и отверстия плиты' })).toBeNull();
    expect(screen.queryByTestId('floor3d-heights')).toBeNull();
    expect(screen.getByRole('button', { name: 'Измерить' })).toBeInTheDocument();
  });

  it('щелчок по отверстию плашку решения не открывает', async () => {
    mount(true);
    fireEvent.click(await screen.findByRole('button', { name: 'щелчок по отверстию' }));
    expect(screen.queryByRole('dialog', { name: 'Отверстие плиты' })).toBeNull();
  });

  it('без readOnly выгрузка DXF и высоты на месте', async () => {
    mount(false);
    expect(await screen.findByRole('button', { name: 'Высоты и отверстия плиты' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Скачать 3D DXF' })).toBeInTheDocument();
  });
});
