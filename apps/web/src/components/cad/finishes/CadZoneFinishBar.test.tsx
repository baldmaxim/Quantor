import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { IWorkspaceCadZones } from '@/components/workspace/cad/types';
import { CadZonesPanel } from '@/components/cad/viewer/CadZonesPanel';
import { zoneFixture } from '@/components/cad/viewer/zoneModeTestUtils';

import { templateFixture } from './finish-fixtures';

const ZONES = [
  zoneFixture({
    id: 'a',
    kind: 'room_mop',
    name: 'Холл 1',
    room_type: 'lift_hall',
    room_type_source: 'derived',
    area_m2: 5,
    calibration_missing: false,
  }),
  zoneFixture({
    id: 'b',
    kind: 'room_mop',
    name: 'Холл 2',
    room_type: 'lift_hall',
    room_type_source: 'manual',
    area_m2: 6,
    calibration_missing: false,
  }),
  zoneFixture({
    id: 'c',
    kind: 'room_apartment',
    apartment_no: '1',
    name: 'Кухня',
    room_type: 'kitchen',
    room_type_source: 'manual',
    area_m2: 9,
    calibration_missing: false,
  }),
  zoneFixture({
    id: 'd',
    kind: 'door',
    name: null,
    room_type: null,
    area_m2: null,
    width_m: 0.9,
    door_height_mm: 2100,
    calibration_missing: false,
  }),
];

const props = (patch: Partial<IWorkspaceCadZones> = {}): IWorkspaceCadZones => ({
  zones: ZONES,
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
  parkingType: 'permanent',
  onParkingTypeChange: vi.fn(),
  onSetParkingType: vi.fn(),
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
  shapeEdit: null,
  shapeEditDisabledReason: null,
  onStartEdit: vi.fn(),
  onStartSplit: vi.fn(),
  ...patch,
});

const finish = (onAssign = vi.fn().mockResolvedValue({ assigned: 2, skipped: 0 })) => ({
  templates: [
    templateFixture({ id: 't1', name: 'Холлы' }),
    templateFixture({ id: 't2', name: 'Кухни' }),
  ],
  assigning: false,
  error: null,
  onAssign,
});

describe('тип помещения в списке зон', () => {
  it('выбор только из кодов своего вида; выведенный тип помечен «авто»', () => {
    render(<CadZonesPanel {...props({ onSetRoomType: vi.fn() })} />);
    const mop = screen.getByRole('combobox', { name: 'Тип помещения: Холл 1' });
    const codes = within(mop)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(codes).toContain('Лифтовой холл');
    expect(codes).toContain('Прочее МОП');
    expect(codes).not.toContain('Кухня');
    const apartment = screen.getByRole('combobox', { name: /Тип помещения: .*Кухня/ });
    // 8 кодов квартиры + «Авто (по названию)» у типа, заданного человеком.
    expect(within(apartment).getAllByRole('option')).toHaveLength(9);
    expect(within(apartment).getByRole('option', { name: 'Авто (по названию)' })).toBeTruthy();
    expect(screen.getAllByText('авто')).toHaveLength(1);
  });

  it('у двери выбора типа нет; смена типа вызывает onSetRoomType', () => {
    const onSetRoomType = vi.fn();
    render(<CadZonesPanel {...props({ onSetRoomType })} />);
    expect(screen.getAllByRole('combobox', { name: /^Тип помещения:/ })).toHaveLength(3);
    fireEvent.change(screen.getByRole('combobox', { name: 'Тип помещения: Холл 1' }), {
      target: { value: 'corridor' },
    });
    expect(onSetRoomType).toHaveBeenCalledWith('a', 'corridor');
  });
});

describe('выбор зон и назначение шаблона', () => {
  it('чекбоксы только у помещений; «выбрать все на листе» - без дверей', () => {
    render(<CadZonesPanel {...props({ finish: finish() })} />);
    expect(screen.getAllByRole('checkbox')).toHaveLength(3);
    fireEvent.click(screen.getByRole('button', { name: 'Выбрать все на листе' }));
    expect(screen.getAllByRole('checkbox').every((box) => (box as HTMLInputElement).checked)).toBe(
      true,
    );
    expect(screen.getByText('Выбрано зон: 3')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Снять выбор' }));
    expect(screen.getByText('Выбрано зон: 0')).toBeInTheDocument();
  });

  it('«выбрать по типу» выбирает зоны этого типа', () => {
    render(<CadZonesPanel {...props({ finish: finish() })} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Выбрать зоны по типу помещения' }), {
      target: { value: 'lift_hall' },
    });
    expect(screen.getByText('Выбрано зон: 2')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Выбрать зону: Холл 1' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Кухня/ })).not.toBeChecked();
  });

  it('«Назначить шаблон…» передаёт выбранные зоны и шаблон, потом сбрасывает выбор', async () => {
    const onAssign = vi.fn().mockResolvedValue({ assigned: 2, skipped: 0 });
    render(<CadZonesPanel {...props({ finish: finish(onAssign) })} />);
    expect(screen.getByRole('button', { name: 'Назначить шаблон…' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать зону: Холл 1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать зону: Холл 2' }));
    fireEvent.click(screen.getByRole('button', { name: 'Назначить шаблон…' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Шаблон отделки для назначения' }), {
      target: { value: 't1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Назначить' }));
    await waitFor(() => expect(screen.getByText('Назначено зонам: 2.')).toBeInTheDocument());
    expect(onAssign).toHaveBeenCalledWith(['a', 'b'], 't1');
    expect(screen.getByText('Выбрано зон: 0')).toBeInTheDocument();
  });

  it('снятие явного назначения передаёт null; пропуски показаны', async () => {
    const onAssign = vi.fn().mockResolvedValue({ assigned: 1, skipped: 1 });
    render(<CadZonesPanel {...props({ finish: finish(onAssign) })} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать зону: Холл 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Назначить шаблон…' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Шаблон отделки для назначения' }), {
      target: { value: '__clear__' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Назначить' }));
    await waitFor(() =>
      expect(screen.getByText('Назначено зонам: 1, пропущено: 1.')).toBeInTheDocument(),
    );
    expect(onAssign).toHaveBeenCalledWith(['a'], null);
  });

  it('отказ: выбор остаётся, ошибка видна', async () => {
    const onAssign = vi.fn().mockResolvedValue(null);
    render(<CadZonesPanel {...props({ finish: { ...finish(onAssign), error: 'Не вышло' } })} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать зону: Холл 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Назначить шаблон…' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Шаблон отделки для назначения' }), {
      target: { value: 't2' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Назначить' }));
    await waitFor(() => expect(onAssign).toHaveBeenCalled());
    expect(screen.getByText('Выбрано зон: 1')).toBeInTheDocument();
    expect(screen.getByText('Не вышло')).toBeInTheDocument();
  });

  it('без finish чекбоксов и панели нет', () => {
    render(<CadZonesPanel {...props()} />);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.queryByTestId('cad-zone-finish-bar')).toBeNull();
  });
});
