import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadLayersPanel } from './CadLayersPanel';

const mount = (patch: Partial<Parameters<typeof CadLayersPanel>[0]> = {}) => {
  const onToggleLayer = vi.fn();
  const onSetLayersHidden = vi.fn();
  const onPdfOpacityChange = vi.fn();
  const onRegionsVisibleChange = vi.fn();
  render(
    <CadLayersPanel
      layers={['WALLS', 'DOORS', 'TEXT']}
      visibleLayers={new Set([0, 2])}
      onToggleLayer={onToggleLayer}
      onSetLayersHidden={onSetLayersHidden}
      pdfOpacity={0.4}
      onPdfOpacityChange={onPdfOpacityChange}
      pdfOpacityActive
      cadShown
      previewAvailable
      pointCount={12345}
      cropAvailable
      cropVisible={false}
      onCropChange={vi.fn()}
      regionsVisible={false}
      onRegionsVisibleChange={onRegionsVisibleChange}
      regionsAvailable
      {...patch}
    />,
  );
  return { onToggleLayer, onSetLayersHidden, onPdfOpacityChange, onRegionsVisibleChange };
};

describe('CadLayersPanel', () => {
  it('у каждого слоя свой цветной образец из токенов палитры по порядку', () => {
    mount();
    const swatches = screen.getAllByTestId('layer-swatch');
    expect(swatches).toHaveLength(3);
    expect(swatches.map((swatch) => swatch.getAttribute('style'))).toEqual([
      expect.stringContaining('var(--cad-layer-1)'),
      expect.stringContaining('var(--cad-layer-2)'),
      expect.stringContaining('var(--cad-layer-3)'),
    ]);
  });

  it('выключенный слой приглушён: образец бледный, имя зачёркнуто и серое', () => {
    mount();
    const [walls, doors] = screen.getAllByTestId('layer-swatch');
    expect(walls).toHaveAttribute('data-layer-on', 'true');
    expect(walls?.className).not.toContain('opacity-30');
    expect(doors).toHaveAttribute('data-layer-on', 'false');
    expect(doors?.className).toContain('opacity-30');
    expect(screen.getByText('DOORS').className).toContain('line-through');
    expect(screen.getByText('WALLS').className).not.toContain('line-through');
  });

  it('чекбокс слоя называется по имени слоя и переключает его', () => {
    const { onToggleLayer } = mount();
    expect(screen.getByRole('checkbox', { name: 'WALLS' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'DOORS' })).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: 'DOORS' }));
    expect(onToggleLayer).toHaveBeenCalledWith(1);
  });

  it('ползунок называется «Непрозрачность PDF» и меняет прозрачность подложки', () => {
    const { onPdfOpacityChange } = mount();
    expect(screen.getByText('Непрозрачность PDF')).toBeInTheDocument();
    expect(screen.queryByText('Непрозрачность CAD')).toBeNull();
    const slider = screen.getByRole('slider');
    expect(slider).toHaveAttribute('aria-valuetext', '40 %');
    expect(slider).toBeEnabled();
    fireEvent.change(slider, { target: { value: '0.7' } });
    expect(onPdfOpacityChange).toHaveBeenCalledWith(0.7);
  });

  it('DXF не наложен - ползунок заблокирован и объясняет почему', () => {
    mount({ pdfOpacityActive: false });
    expect(screen.getByRole('slider')).toBeDisabled();
    expect(screen.getByText(/действует, когда DXF наложен на лист/)).toBeInTheDocument();
  });

  it('область проверки масштаба и число точек', () => {
    mount();
    expect(
      screen.getByRole('checkbox', { name: 'Область проверки масштаба на PDF' }),
    ).not.toBeChecked();
    expect(screen.getByText(/Точек в предпросмотре/)).toHaveTextContent('12');
  });

  it('геометрия CAD не показана: слоёв нет, причина названа', () => {
    mount({ cadShown: false, pdfOpacityActive: false });
    expect(screen.queryByTestId('layer-swatch')).toBeNull();
    expect(screen.getByText(/Геометрия CAD пока не наложена/)).toBeInTheDocument();
  });

  it('предпросмотра нет совсем: другая причина, ползунка нет', () => {
    mount({ cadShown: false, previewAvailable: false, layers: [], pointCount: null });
    expect(screen.getByText(/предпросмотр геометрии не получен/)).toBeInTheDocument();
    expect(screen.queryByRole('slider')).toBeNull();
    expect(screen.queryByText(/Точек в предпросмотре/)).toBeNull();
  });

  it('слои сгруппированы по типу, пустые группы не показаны', () => {
    mount({ layers: ['A-WALL', 'DOORS', '0', 'WALLS-2'], visibleLayers: new Set([0, 1, 2, 3]) });
    expect(screen.getByRole('checkbox', { name: 'Группа «Стены»' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Группа «Двери»' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Группа «Прочее»' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Группа «Окна»' })).toBeNull();
    expect(screen.getByTestId('layer-group-walls')).toHaveTextContent('2 / 2');
  });

  it('переключатель группы скрывает все слои группы разом', () => {
    const { onSetLayersHidden } = mount({
      layers: ['A-WALL', 'DOORS', 'WALLS-2'],
      visibleLayers: new Set([0, 1, 2]),
    });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Группа «Стены»' }));
    expect(onSetLayersHidden).toHaveBeenCalledWith([0, 2], true);
  });

  it('частично видимая группа: неопределённое состояние; щелчок показывает все слои', () => {
    const { onSetLayersHidden } = mount({
      layers: ['A-WALL', 'WALLS-2'],
      visibleLayers: new Set([0]),
    });
    const master = screen.getByRole('checkbox', { name: 'Группа «Стены»' }) as HTMLInputElement;
    expect(master.indeterminate).toBe(true);
    expect(master.checked).toBe(false);
    fireEvent.click(master);
    expect(onSetLayersHidden).toHaveBeenCalledWith([0, 1], false);
  });

  it('полностью скрытая группа не неопределённая и показывается целиком', () => {
    const { onSetLayersHidden } = mount({ layers: ['DOORS'], visibleLayers: new Set<number>() });
    const master = screen.getByRole('checkbox', { name: 'Группа «Двери»' }) as HTMLInputElement;
    expect(master.indeterminate).toBe(false);
    fireEvent.click(master);
    expect(onSetLayersHidden).toHaveBeenCalledWith([0], false);
  });

  it('заголовок группы сворачивает слои; общий чекбокс при этом не срабатывает', () => {
    const { onSetLayersHidden } = mount({ layers: ['DOORS'], visibleLayers: new Set([0]) });
    const toggle = screen.getByRole('button', { name: /Двери/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('checkbox', { name: 'DOORS' })).toBeVisible();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('checkbox', { name: 'DOORS', hidden: true })).not.toBeVisible();
    expect(onSetLayersHidden).not.toHaveBeenCalled();
  });

  it('флажок «Распознанные блоки» отражает состояние и вызывает обработчик', () => {
    const { onRegionsVisibleChange } = mount();
    const box = screen.getByRole('checkbox', { name: 'Распознанные блоки' });
    expect(box).not.toBeChecked();
    expect(box).toBeEnabled();
    expect(screen.getByText('Области распознавания поверх PDF')).toBeInTheDocument();
    fireEvent.click(box);
    expect(onRegionsVisibleChange).toHaveBeenCalledWith(true);
  });

  it('флажок «Распознанные блоки» показан и без DXF', () => {
    mount({ layers: [], cadShown: false, previewAvailable: false, regionsVisible: true });
    expect(screen.getByRole('checkbox', { name: 'Распознанные блоки' })).toBeChecked();
  });

  it('при выключенном слое распознавания флажок недоступен и объясняет причину', () => {
    mount({ regionsAvailable: false, regionsVisible: true });
    const box = screen.getByRole('checkbox', { name: 'Распознанные блоки' });
    expect(box).toBeDisabled();
    expect(box).not.toBeChecked();
    expect(screen.getByText('Слой распознавания выключен на панели инструментов')).toBeInTheDocument();
  });
});
