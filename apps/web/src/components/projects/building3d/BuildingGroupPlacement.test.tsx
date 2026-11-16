import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BuildingGroupPlacement } from './BuildingGroupPlacement';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  revokeSitePin: vi.fn(),
}));

const group = (patch: Partial<client.CadBuilding3dGroupRead>): client.CadBuilding3dGroupRead =>
  ({
    key: 'k2',
    label: 'К2 · С1',
    floor_count: 3,
    aligned_count: 3,
    placement: 'none',
    placement_message: 'нет общих осей',
    ...patch,
  }) as client.CadBuilding3dGroupRead;

const mount = (g: client.CadBuilding3dGroupRead, canEdit: boolean, onPin = vi.fn()) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
  render(
    <QueryClientProvider client={queryClient}>
      <BuildingGroupPlacement projectId="p1" group={g} canEdit={canEdit} onPin={onPin} />
    </QueryClientProvider>,
  );
  return { onPin, invalidate };
};

beforeEach(() => {
  vi.mocked(client.revokeSitePin).mockResolvedValue({ data: { id: 'pin-1' } } as never);
});
afterEach(cleanup);

describe('посадка здания в списке', () => {
  it('не поставлен: причина и кнопка «Привязать вручную» с правом записи', () => {
    const { onPin } = mount(group({}), true);
    expect(screen.getByText('Не поставлен на объект: нет общих осей')).toBeInTheDocument();
    const g = group({});
    fireEvent.click(screen.getByRole('button', { name: 'Привязать вручную' }));
    expect(onPin).toHaveBeenCalledWith(expect.objectContaining({ key: g.key }));
  });

  it('без права записи кнопки нет, причина остаётся', () => {
    mount(group({}), false);
    expect(screen.queryByRole('button', { name: 'Привязать вручную' })).toBeNull();
    expect(screen.getByText(/Не поставлен на объект/)).toBeInTheDocument();
  });

  it('поставленные другим способом - ничего не показывает', () => {
    mount(group({ placement: 'axes' }), true);
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByText(/Не поставлен/)).toBeNull();
  });

  it('привязан вручную: подпись с сообщением; кнопка «Снять привязку» только с правом записи', () => {
    const manual = group({ placement: 'manual', site_pin_id: 'pin-1', placement_message: 'невязка 12 мм' });
    mount(manual, false);
    expect(screen.getByText('Привязан вручную: невязка 12 мм')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Снять привязку' })).toBeNull();
  });

  it('«Снять привязку»: подтверждение, затем DELETE и перечитывание здания', async () => {
    const manual = group({ placement: 'manual', site_pin_id: 'pin-1' });
    const { invalidate } = mount(manual, true);
    fireEvent.click(screen.getByRole('button', { name: 'Снять привязку' }));
    expect(client.revokeSitePin).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('dialog', { name: 'Снять привязку?' });
    fireEvent.click(dialog.querySelector('footer button:last-child') as HTMLElement);
    await waitFor(() =>
      expect(client.revokeSitePin).toHaveBeenCalledWith(
        expect.objectContaining({ path: { project_id: 'p1', pin_id: 'pin-1' } }),
      ),
    );
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['cad-building3d', 'p1'] }),
    );
  });

  it('отмена подтверждения ничего не отправляет', async () => {
    mount(group({ placement: 'manual', site_pin_id: 'pin-1' }), true);
    fireEvent.click(screen.getByRole('button', { name: 'Снять привязку' }));
    const dialog = await screen.findByRole('dialog', { name: 'Снять привязку?' });
    fireEvent.click(dialog.querySelector('footer button:first-child') as HTMLElement);
    expect(client.revokeSitePin).not.toHaveBeenCalled();
  });

  it('ошибка сервера при снятии показана в окне подтверждения', async () => {
    vi.mocked(client.revokeSitePin).mockRejectedValue({ detail: { code: 'CAD_SITE_PIN_ALREADY_REVOKED', message: 'Привязка уже снята.' } });
    mount(group({ placement: 'manual', site_pin_id: 'pin-1' }), true);
    fireEvent.click(screen.getByRole('button', { name: 'Снять привязку' }));
    const dialog = await screen.findByRole('dialog', { name: 'Снять привязку?' });
    fireEvent.click(dialog.querySelector('footer button:last-child') as HTMLElement);
    expect(await screen.findByRole('alert')).toHaveTextContent('Привязка уже снята.');
  });
});
