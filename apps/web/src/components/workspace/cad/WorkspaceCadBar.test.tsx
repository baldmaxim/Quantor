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
    mode: 'overlay',
    dxfAvailable: true,
    dxfReason: null,
    onModeChange: vi.fn(),
    onZoomIn: vi.fn(),
    onZoomOut: vi.fn(),
    onFit: vi.fn(),
    notices: [],
    loading: false,
    ...patch,
  };
  render(<WorkspaceCadBar {...props} />);
  return props;
};

describe('WorkspaceCadBar', () => {
  it('заголовок вида, режимы PDF / CAD / Наложение и масштаб', () => {
    mount();
    expect(screen.getByText(/Стр\. 1 · вид 1/)).toBeInTheDocument();
    const modes = screen.getByRole('group', { name: 'Что показывать' });
    expect(modes).toHaveTextContent('PDF');
    expect(modes).toHaveTextContent('CAD');
    expect(modes).toHaveTextContent('Наложение');
    expect(screen.getByRole('button', { name: 'Наложение' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('режим меняется кликом', () => {
    const props = mount();
    fireEvent.click(screen.getByRole('button', { name: 'CAD' }));
    expect(props.onModeChange).toHaveBeenCalledWith('cad');
  });

  it('кнопки масштаба идут в камеру рабочей области', () => {
    const props = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Увеличить' }));
    fireEvent.click(screen.getByRole('button', { name: 'Уменьшить' }));
    fireEvent.click(screen.getByRole('button', { name: 'Вписать' }));
    expect(props.onZoomIn).toHaveBeenCalledTimes(1);
    expect(props.onZoomOut).toHaveBeenCalledTimes(1);
    expect(props.onFit).toHaveBeenCalledTimes(1);
  });

  it('DXF накладывать нельзя: CAD и наложение закрыты, причина в подсказке и в строке', () => {
    mount({
      mode: 'pdf',
      dxfAvailable: false,
      dxfReason: 'Кадр координат не подтверждён: DXF не накладывается.',
      notices: [{ tone: 'note', text: 'Кадр координат не подтверждён: DXF не накладывается.' }],
    });
    expect(screen.getByRole('button', { name: 'CAD' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Наложение' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'PDF' })).toBeEnabled();
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
