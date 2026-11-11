import type { CadZoneRead } from '@quantor/api-client';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { templateFixture } from '@/components/cad/finishes/finish-fixtures';

import { CadZoneList } from './CadZoneList';
import { zoneFixture } from './zoneModeTestUtils';

const room = (
  id: string,
  apartmentNo: string,
  area: number | null,
  patch: Partial<CadZoneRead> = {},
) =>
  zoneFixture({
    id,
    kind: 'room_apartment',
    apartment_no: apartmentNo,
    room_mark: `М-${id}`,
    area_m2: area,
    calibration_missing: area === null,
    ...patch,
  });

const ZONES: readonly CadZoneRead[] = [
  room('a1', '12', 10),
  room('a2', '12', 5.5, { room_type: 'kitchen', room_type_source: 'derived', name: 'Кухня' }),
  room('b1', '7', 20),
  zoneFixture({
    id: 'm1',
    kind: 'room_mop',
    room_mark: 'МОП-1',
    area_m2: 8,
    calibration_missing: false,
  }),
  zoneFixture({
    id: 'd1',
    kind: 'door',
    width_m: 0.9,
    door_height_mm: 2100,
    calibration_missing: false,
  }),
];

const baseProps = {
  zones: ZONES,
  activeId: null,
  saving: false,
  onActivate: vi.fn(),
  onRename: vi.fn(),
  onDelete: vi.fn(),
};

describe('CadZoneList', () => {
  it('сводка над списком: квартиры, помещения, площадь, МОП, двери', () => {
    render(<CadZoneList {...baseProps} />);
    const summary = screen.getByTestId('cad-zone-summary');
    expect(summary).toHaveTextContent('Квартир: 2 · помещений: 3 · 35,50 м²');
    expect(summary).toHaveTextContent('МОП: 8,00 м² · Дверей: 1');
    expect(summary).not.toHaveTextContent('Машино-мест');
  });

  it('неопределённая площадь не превращается в 0 и помечается', () => {
    render(<CadZoneList {...baseProps} zones={[room('a', '1', 4), room('b', '1', null)]} />);
    expect(screen.getByTestId('cad-zone-summary')).toHaveTextContent('4,00 м² (не у всех)');
    expect(screen.getByRole('heading', { name: /Кв\. 1/ })).toHaveTextContent(
      '2 пом. · 4,00 м² (не у всех)',
    );
  });

  it('по умолчанию всё свёрнуто; квартиры в порядке номеров', () => {
    render(<CadZoneList {...baseProps} />);
    const headers = screen.getAllByRole('button', { expanded: false });
    expect(headers.map((button) => button.textContent)).toEqual([
      expect.stringContaining('Кв. 7'),
      expect.stringContaining('Кв. 12'),
      expect.stringContaining('МОП'),
      expect.stringContaining('Двери: 1 шт.'),
    ]);
    expect(screen.queryByText('М-a1')).toBeNull();
  });

  it('раскрывается одна квартира, потом все, потом сворачиваются все', () => {
    render(<CadZoneList {...baseProps} />);
    fireEvent.click(screen.getByRole('button', { name: /Кв\. 12/ }));
    expect(screen.getByRole('button', { name: /Кв\. 12/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByText('М-a1')).toBeInTheDocument();
    expect(screen.getByText('М-a2 · Кухня')).toBeInTheDocument();
    expect(screen.getByText('Кухня · авто')).toBeInTheDocument();
    expect(screen.queryByText('М-b1')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Развернуть все' }));
    expect(screen.getByText('М-b1')).toBeInTheDocument();
    expect(screen.getByText('900 × 2100 мм')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Свернуть все' }));
    expect(screen.queryByText('М-a1')).toBeNull();
    expect(screen.queryByText('М-b1')).toBeNull();
  });

  it('в строках нет кнопок действий, пока зона не выделена', () => {
    const onActivate = vi.fn();
    const { rerender } = render(<CadZoneList {...baseProps} onActivate={onActivate} />);
    fireEvent.click(screen.getByRole('button', { name: 'Развернуть все' }));
    expect(screen.queryByRole('button', { name: 'Переименовать' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Удалить' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /М-b1/ }));
    expect(onActivate).toHaveBeenCalledWith('b1');
    rerender(<CadZoneList {...baseProps} onActivate={onActivate} activeId="b1" />);
    expect(screen.getAllByRole('button', { name: 'Переименовать' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: /М-b1/ })).toHaveAttribute('aria-pressed', 'true');
  });

  it('выделение с холста раскрывает группу зоны', () => {
    const { rerender } = render(<CadZoneList {...baseProps} />);
    expect(screen.queryByText('МОП-1')).toBeNull();
    rerender(<CadZoneList {...baseProps} activeId="m1" />);
    expect(screen.getByRole('button', { name: /^МОП1 пом\./ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByText('МОП-1')).toBeInTheDocument();
    expect(screen.queryByText('М-a1')).toBeNull();
  });

  it('флажок группы выбирает все помещения квартиры (только в режиме выбора)', () => {
    const onAssign = vi.fn().mockResolvedValue({ assigned: 2, skipped: 0 });
    render(
      <CadZoneList
        {...baseProps}
        finish={{
          templates: [templateFixture({ id: 't1', name: 'Кв' })],
          assigning: false,
          error: null,
          onAssign,
        }}
      />,
    );
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Шаблон отделки…' }));
    expect(screen.getByTestId('cad-zone-finish-bar')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать все помещения: Кв. 12' }));
    expect(screen.getByText('Выбрано зон: 2')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Выбрать все помещения: Кв. 12' })).toBeChecked();
    expect(
      screen.getByRole('checkbox', { name: 'Выбрать все помещения: Кв. 7' }),
    ).not.toBeChecked();

    fireEvent.click(screen.getByRole('button', { name: 'Развернуть все' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать зону: М-a1' }));
    expect(screen.getByText('Выбрано зон: 1')).toBeInTheDocument();
    const group = screen.getByRole('checkbox', {
      name: 'Выбрать все помещения: Кв. 12',
    }) as HTMLInputElement;
    expect(group.indeterminate).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Готово' }));
    expect(screen.queryByTestId('cad-zone-finish-bar')).toBeNull();
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
  });
});
