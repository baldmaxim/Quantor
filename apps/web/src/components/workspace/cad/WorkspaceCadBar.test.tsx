import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { diagnostics } from '@/components/cad/viewer/fixtures';

import type { IWorkspaceCadBarProps } from './types';
import { WorkspaceCadBar } from './WorkspaceCadBar';

const mount = (patch: Partial<IWorkspaceCadBarProps> = {}) => {
  const props: IWorkspaceCadBarProps = {
    diagnostics: diagnostics(),
    views: [1],
    view: 1,
    onViewChange: vi.fn(),
    onFit: vi.fn(),
    notices: [],
    loading: false,
    ...patch,
  };
  render(<WorkspaceCadBar {...props} />);
  return props;
};

describe('WorkspaceCadBar', () => {
  it('заголовок вида и «Вписать»; переключателя режимов и кнопок +/− нет', () => {
    mount();
    expect(screen.getByText(/Стр\. 1 · вид 1/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Вписать' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Что показывать' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'PDF' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'CAD' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Наложение' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Увеличить' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Уменьшить' })).toBeNull();
  });

  it('«Вписать» идёт в камеру рабочей области', () => {
    const props = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Вписать' }));
    expect(props.onFit).toHaveBeenCalledTimes(1);
  });

  it('DXF накладывать нельзя: причина в строке предупреждений', () => {
    mount({
      notices: [{ tone: 'note', text: 'Кадр координат не подтверждён: DXF не накладывается.' }],
    });
    expect(screen.getByRole('note')).toHaveTextContent('Кадр координат не подтверждён');
  });

  it('несколько видов: переключатель вида', () => {
    const props = mount({ views: [1, 2, 3], view: 2 });
    fireEvent.click(screen.getByRole('button', { name: 'Вид 3' }));
    expect(props.onViewChange).toHaveBeenCalledWith(3);
  });

  it('один вид: переключателя нет', () => {
    mount();
    expect(screen.queryByRole('group', { name: 'Вид листа' })).toBeNull();
  });

  it('загрузка геометрии и ошибка предпросмотра', () => {
    mount({ loading: true, notices: [{ tone: 'alert', text: 'Предпросмотр не принят' }] });
    expect(screen.getByRole('status')).toHaveTextContent('Загрузка геометрии CAD');
    expect(screen.getByRole('alert')).toHaveTextContent('Предпросмотр не принят');
  });
});
