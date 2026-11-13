import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useWorkspaceStore } from '@/store/workspace';

import { CadLayersPanel } from './CadLayersPanel';

const mount = (patch: Partial<Parameters<typeof CadLayersPanel>[0]> = {}) => {
  const onToggleLayer = vi.fn();
  const onSetLayersHidden = vi.fn();
  const onPdfOpacityChange = vi.fn();
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
      {...patch}
    />,
  );
  return { onToggleLayer, onSetLayersHidden, onPdfOpacityChange };
};

describe('CadLayersPanel', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ overlayVisible: false });
  });

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
    expect(screen.getByRole('checkbox', { name: 'Группа «Кладка и перегородки»' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Группа «Двери и ворота»' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Группа «Прочее»' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Группа «Окна»' })).toBeNull();
    expect(screen.getByTestId('layer-group-walls')).toHaveTextContent('2 / 2');
  });

  it('служебные слои и 02_МОНОЛИТ в списке «Чертёж» не показаны', () => {
    mount({
      layers: ['01_КЛАДКА_100', '02_МОНОЛИТ', 'AUX_КОНТУРЫ_СТЕН', 'QA_МАРКЕРЫ_НЕ_УЧИТЫВАТЬ'],
      visibleLayers: new Set([0, 1, 2, 3]),
    });
    expect(screen.getAllByTestId('layer-swatch')).toHaveLength(1);
    expect(screen.queryByRole('checkbox', { name: '02_МОНОЛИТ' })).toBeNull();
    expect(screen.queryByRole('checkbox', { name: 'Группа «Прочее»' })).toBeNull();
  });

  it('строки «Конструкции листа» по порядку, с числами; нет данных - без числа', () => {
    const categories = {
      monolithVertical: true,
      monolithColumn: false,
      slab: true,
      onChange: vi.fn(),
    };
    mount({
      categories,
      counts: { monolithVertical: 12, monolithColumn: 0, slab: 3, masonry: 1234, doors: 7 },
      layers: ['01_КЛАДКА_100', '03_ДВЕРИ_БЛОКИ', '04_ОКНА'],
      visibleLayers: new Set([0, 1, 2]),
    });
    const rows = within(screen.getByTestId('category-layers')).getAllByRole('checkbox');
    expect(rows.map((row) => row.closest('label')?.textContent)).toEqual([
      'Монолит — стены и пилоны12',
      'Монолит — колонны0',
      'Плита3',
    ]);
    expect(screen.getByTestId('layer-group-walls')).toHaveTextContent('1 / 1');
    const counts = screen.getAllByTestId('layer-group-count').map((node) => node.textContent);
    expect(counts.map((text) => text?.replace(/\D/g, ''))).toEqual(['1234', '7']);
    expect(within(screen.getByTestId('layer-group-windows')).queryByTestId('layer-group-count')).toBeNull();
    fireEvent.click(rows[1] as HTMLElement);
    expect(categories.onChange).toHaveBeenLastCalledWith('monolith_column', true);
  });

  it('без данных конструкций чисел нет вовсе', () => {
    mount({
      categories: { monolithVertical: true, monolithColumn: true, slab: true, onChange: vi.fn() },
      counts: null,
    });
    expect(screen.queryByTestId('category-count')).toBeNull();
    expect(screen.queryByTestId('layer-group-count')).toBeNull();
  });

  it('переключатель группы скрывает все слои группы разом', () => {
    const { onSetLayersHidden } = mount({
      layers: ['A-WALL', 'DOORS', 'WALLS-2'],
      visibleLayers: new Set([0, 1, 2]),
    });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Группа «Кладка и перегородки»' }));
    expect(onSetLayersHidden).toHaveBeenCalledWith([0, 2], true);
  });

  it('частично видимая группа: неопределённое состояние; щелчок показывает все слои', () => {
    const { onSetLayersHidden } = mount({
      layers: ['A-WALL', 'WALLS-2'],
      visibleLayers: new Set([0]),
    });
    const master = screen.getByRole('checkbox', { name: 'Группа «Кладка и перегородки»' }) as HTMLInputElement;
    expect(master.indeterminate).toBe(true);
    expect(master.checked).toBe(false);
    fireEvent.click(master);
    expect(onSetLayersHidden).toHaveBeenCalledWith([0, 1], false);
  });

  it('полностью скрытая группа не неопределённая и показывается целиком', () => {
    const { onSetLayersHidden } = mount({ layers: ['DOORS'], visibleLayers: new Set<number>() });
    const master = screen.getByRole('checkbox', { name: 'Группа «Двери и ворота»' }) as HTMLInputElement;
    expect(master.indeterminate).toBe(false);
    fireEvent.click(master);
    expect(onSetLayersHidden).toHaveBeenCalledWith([0], false);
  });

  it('заголовок группы сворачивает слои; общий чекбокс при этом не срабатывает', () => {
    const { onSetLayersHidden } = mount({ layers: ['DOORS'], visibleLayers: new Set([0]) });
    const toggle = screen.getByRole('button', { name: /Двери и ворота/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('checkbox', { name: 'DOORS' })).toBeVisible();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('checkbox', { name: 'DOORS', hidden: true })).not.toBeVisible();
    expect(onSetLayersHidden).not.toHaveBeenCalled();
  });

  it('флажок «Распознанные блоки» переключает общее состояние показа блоков', () => {
    mount();
    const box = screen.getByRole('checkbox', { name: 'Распознанные блоки' });
    expect(box).not.toBeChecked();
    expect(box).toBeEnabled();
    expect(screen.getByText('Области распознавания поверх PDF')).toBeInTheDocument();
    fireEvent.click(box);
    expect(useWorkspaceStore.getState().overlayVisible).toBe(true);
    expect(box).toBeChecked();
    fireEvent.click(box);
    expect(useWorkspaceStore.getState().overlayVisible).toBe(false);
  });

  it('флажок «Распознанные блоки» отражает общее состояние и без DXF', () => {
    useWorkspaceStore.setState({ overlayVisible: true });
    mount({ layers: [], cadShown: false, previewAvailable: false });
    expect(screen.getByRole('checkbox', { name: 'Распознанные блоки' })).toBeChecked();
  });
});
