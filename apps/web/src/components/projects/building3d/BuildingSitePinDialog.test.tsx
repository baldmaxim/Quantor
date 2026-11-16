import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BuildingSitePinDialog } from './BuildingSitePinDialog';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  createSitePin: vi.fn(),
}));

// Canvas2D и жесты проверяются отдельно: панель плана - подставка, щелчок ставит заданную точку.
vi.mock('./SitePinPlanCanvas', () => ({
  SitePinPlanCanvas: ({ label, onPick }: { label: string; onPick: (point: [number, number]) => void }) => (
    <div data-testid="plan" data-label={label}>
      <button type="button" onClick={() => onPick([0, 0])}>
        {`${label.split('.')[0]}: поставить A`}
      </button>
      <button type="button" onClick={() => onPick([10000, 0])}>
        {`${label.split('.')[0]}: поставить B`}
      </button>
    </div>
  ),
}));

const floor = (patch: Partial<client.CadBuilding3dFloorRead>): client.CadBuilding3dFloorRead =>
  ({
    job_id: 'j',
    revision_id: 'r',
    page_index: 0,
    view: 0,
    label: '1 этаж',
    group_key: 'k2',
    group_label: 'К2',
    base_z_mm: 0,
    rotation_deg: 0,
    offset_mm: [0, 0],
    outline: [[0, 0], [10000, 0], [10000, 5000], [0, 5000]],
    walls: [],
    ...patch,
  }) as client.CadBuilding3dFloorRead;

const floors = [
  floor({ job_id: 'src', revision_id: 'r-src', page_index: 4, view: 1 }),
  floor({ job_id: 'dst', revision_id: 'r-dst', page_index: 9, view: 0, group_key: 'base', group_label: 'База', label: 'Подземка' }),
];
const groups = [
  { key: 'k2', label: 'К2', placement: 'none' },
  { key: 'base', label: 'База', placement: 'reference' },
] as client.CadBuilding3dGroupRead[];

const mount = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
  const onClose = vi.fn();
  const onCreated = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <BuildingSitePinDialog
        projectId="p1"
        group={groups[0] as client.CadBuilding3dGroupRead}
        groups={groups}
        floors={floors}
        onClose={onClose}
        onCreated={onCreated}
      />
    </QueryClientProvider>,
  );
  return { invalidate, onClose, onCreated };
};

const placeAll = () => {
  fireEvent.click(screen.getByRole('button', { name: 'План: Корпус: поставить A' }));
  fireEvent.click(screen.getByRole('button', { name: 'План: Корпус: поставить B' }));
  fireEvent.click(screen.getByRole('button', { name: 'План: Площадка: поставить A' }));
  fireEvent.click(screen.getByRole('button', { name: 'План: Площадка: поставить B' }));
};

beforeEach(() => {
  vi.mocked(client.createSitePin).mockResolvedValue({
    data: { id: 'pin-1', rotation_deg: 90, offset_x_mm: 1000, offset_y_mm: -2000, residual_mm: 3, baseline_mm: 10000 },
  } as never);
});
afterEach(cleanup);

describe('диалог ручной привязки', () => {
  it('«Привязать» неактивна, пока нет четырёх точек', async () => {
    mount();
    const submit = await screen.findByRole('button', { name: 'Привязать' });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'План: Корпус: поставить A' }));
    fireEvent.click(screen.getByRole('button', { name: 'План: Корпус: поставить B' }));
    fireEvent.click(screen.getByRole('button', { name: 'План: Площадка: поставить A' }));
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'План: Площадка: поставить B' }));
    expect(submit).toBeEnabled();
  });

  it('под панелями - длины отрезков и расхождение как предварительная подсказка', async () => {
    mount();
    placeAll();
    expect(await screen.findByText(/отрезок 1-2 на корпусе 10,00 м, на площадке 10,00 м, расхождение 0,00 %/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('успех: POST с листами и точками, перечитывание здания, ответ уходит наверх, диалог закрыт', async () => {
    const { invalidate, onClose, onCreated } = mount();
    placeAll();
    fireEvent.change(screen.getByLabelText('Примечание'), { target: { value: ' по оси А ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Привязать' }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'pin-1', rotation_deg: 90 })));
    expect(client.createSitePin).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { project_id: 'p1' },
        body: {
          source: { revision_id: 'r-src', page_index: 4, view: 1 },
          target: { revision_id: 'r-dst', page_index: 9, view: 0 },
          source_points: [{ x_mm: 0, y_mm: 0 }, { x_mm: 10000, y_mm: 0 }],
          target_points: [{ x_mm: 0, y_mm: 0 }, { x_mm: 10000, y_mm: 0 }],
          note: 'по оси А',
        },
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['cad-building3d', 'p1'] });
    expect(onClose).toHaveBeenCalled();
  });

  it('422: текст сервера в диалоге, точки не сброшены, диалог открыт', async () => {
    vi.mocked(client.createSitePin).mockRejectedValue({
      detail: { code: 'CAD_SITE_PIN_INVALID', message: 'База слишком короткая: нужно не меньше 5 м.' },
    });
    const { onClose, onCreated } = mount();
    placeAll();
    fireEvent.click(screen.getByRole('button', { name: 'Привязать' }));
    expect(await screen.findByText('База слишком короткая: нужно не меньше 5 м.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Привязать' })).toBeEnabled();
  });

  it('примечание: крестик очищает поле и оставляет в нём фокус', () => {
    mount();
    const note = screen.getByLabelText('Примечание');
    expect(screen.queryByRole('button', { name: 'Очистить: Примечание' })).toBeNull();
    fireEvent.change(note, { target: { value: 'текст' } });
    fireEvent.click(screen.getByRole('button', { name: 'Очистить: Примечание' }));
    expect(note).toHaveValue('');
    expect(note).toHaveFocus();
  });
});
