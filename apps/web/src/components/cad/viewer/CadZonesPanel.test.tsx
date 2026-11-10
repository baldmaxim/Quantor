import type { CadZoneRead } from '@quantor/api-client';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { IWorkspaceCadZones } from '@/components/workspace/cad/types';

import { CadZonesPanel } from './CadZonesPanel';

const zone = (patch: Partial<CadZoneRead>): CadZoneRead => ({
  id: 'z1',
  revision_id: 'r1',
  page_index: 0,
  kind: 'room_apartment',
  apartment_no: '0042',
  room_mark: '3-1/6',
  name: null,
  points: [
    [0.1, 0.1],
    [0.3, 0.1],
    [0.3, 0.3],
  ],
  door_height_mm: null,
  area_m2: 12.5,
  perimeter_m: 14,
  width_m: null,
  calibration_missing: false,
  geometry_issue: null,
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
  ...patch,
});

const props = (patch: Partial<IWorkspaceCadZones> = {}): IWorkspaceCadZones => ({
  zones: [],
  loading: false,
  loadError: null,
  onReload: vi.fn(),
  kind: 'room_apartment',
  onKindChange: vi.fn(),
  apartmentNo: '',
  onApartmentNoChange: vi.fn(),
  roomMark: '',
  onRoomMarkChange: vi.fn(),
  doorHeight: '2100',
  onDoorHeightChange: vi.fn(),
  drawing: false,
  drawDisabledReason: null,
  onStartDrawing: vi.fn(),
  onStopDrawing: vi.fn(),
  activeId: null,
  onActivate: vi.fn(),
  saving: false,
  error: null,
  onRename: vi.fn(),
  onDelete: vi.fn(),
  ...patch,
});

describe('CadZonesPanel', () => {
  it('форма скрыта до нажатия «Отрисовать зону»; затем есть выбор вида и поля квартиры', () => {
    render(<CadZonesPanel {...props()} />);
    expect(screen.queryByTestId('cad-zone-form')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Отрисовать зону' }));
    expect(screen.getByRole('button', { name: 'Помещение квартиры' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'МОП' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Дверь' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '№ квартиры' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Марка помещения' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Высота, мм' })).toBeNull();
  });

  it('у двери - высота, без № квартиры и марки; выбор вида уходит наружу', () => {
    const onKindChange = vi.fn();
    render(<CadZonesPanel {...props({ kind: 'door', onKindChange })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Отрисовать зону' }));
    expect(screen.getByRole('textbox', { name: 'Высота, мм' })).toHaveValue('2100');
    expect(screen.queryByRole('textbox', { name: '№ квартиры' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'МОП' }));
    expect(onKindChange).toHaveBeenCalledWith('room_mop');
  });

  it('«Рисовать» заблокирована с причиной, пока поле не заполнено', () => {
    const onStartDrawing = vi.fn();
    render(
      <CadZonesPanel {...props({ drawDisabledReason: 'Укажите № квартиры.', onStartDrawing })} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Отрисовать зону' }));
    expect(screen.getByRole('button', { name: 'Рисовать' })).toBeDisabled();
    expect(screen.getByText('Укажите № квартиры.')).toBeInTheDocument();
  });

  it('«Рисовать» запускает режим; в режиме есть подсказка и «Закончить рисование»', () => {
    const onStartDrawing = vi.fn();
    const onStopDrawing = vi.fn();
    const { rerender } = render(
      <CadZonesPanel {...props({ apartmentNo: '12', onStartDrawing })} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Отрисовать зону' }));
    fireEvent.click(screen.getByRole('button', { name: 'Рисовать' }));
    expect(onStartDrawing).toHaveBeenCalledTimes(1);

    rerender(<CadZonesPanel {...props({ apartmentNo: '12', drawing: true, onStopDrawing })} />);
    expect(screen.getByText(/Enter, двойной щелчок/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Закончить рисование' }));
    expect(onStopDrawing).toHaveBeenCalledTimes(1);
  });

  it('список: группы с суммами, «нет калибровки» вместо нуля', () => {
    render(
      <CadZonesPanel
        {...props({
          zones: [
            zone({ id: 'a', area_m2: 10 }),
            zone({ id: 'b', area_m2: 2.5 }),
            zone({
              id: 'c',
              kind: 'room_mop',
              apartment_no: null,
              area_m2: null,
              calibration_missing: true,
            }),
            zone({
              id: 'd',
              kind: 'door',
              apartment_no: null,
              room_mark: null,
              area_m2: null,
              perimeter_m: null,
              width_m: 0.9,
              door_height_mm: 2100,
            }),
          ],
        })}
      />,
    );
    const apartment = screen.getByRole('heading', { name: /Квартира 0042/ });
    expect(apartment).toHaveTextContent('12,50');
    const mop = screen.getByRole('heading', { name: /МОП/ });
    expect(mop).toHaveTextContent('нет калибровки');
    expect(mop).not.toHaveTextContent('0,00');
    expect(screen.getByRole('heading', { name: /Двери/ })).toHaveTextContent('1 шт.');
    expect(screen.getByText('900 × 2100 мм')).toBeInTheDocument();
  });

  it('строка: выделить, переименовать (Enter), удалить с подтверждением', () => {
    const onActivate = vi.fn();
    const onRename = vi.fn();
    const onDelete = vi.fn();
    render(
      <CadZonesPanel {...props({ zones: [zone({ id: 'a' })], onActivate, onRename, onDelete })} />,
    );
    const list = screen.getByTestId('cad-zone-list');
    fireEvent.click(within(list).getByRole('button', { name: /3-1\/6/ }));
    expect(onActivate).toHaveBeenCalledWith('a');

    fireEvent.click(within(list).getByRole('button', { name: 'Переименовать' }));
    const field = within(list).getByRole('textbox', { name: 'Название зоны' });
    fireEvent.change(field, { target: { value: 'Кухня' } });
    fireEvent.submit(field.closest('form') as HTMLFormElement);
    expect(onRename).toHaveBeenCalledWith('a', 'Кухня');

    fireEvent.click(within(list).getByRole('button', { name: 'Удалить' }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(within(list).getByText('Удалить зону?')).toBeInTheDocument();
    fireEvent.click(within(list).getAllByRole('button', { name: 'Удалить' })[0] as HTMLElement);
    expect(onDelete).toHaveBeenCalledWith('a');
  });

  it('отказ сервера и ошибка загрузки показываются, повтор перечитывает список', () => {
    const onReload = vi.fn();
    render(
      <CadZonesPanel {...props({ error: 'Контур пересекается', loadError: 'сеть', onReload })} />,
    );
    expect(screen.getByText('Контур пересекается')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onReload).toHaveBeenCalledTimes(1);
  });
});
