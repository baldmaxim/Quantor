import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { WorkspaceShell } from './WorkspaceShell';
import { PANE_LIMITS, useWorkspaceStore } from '@/store/workspace';

/**
 * Каркас рабочей области.
 *
 * Проверяется то, ради чего он и написан: панели сворачиваются и меняют ширину,
 * центр остаётся слотом, а разделитель управляется с клавиатуры.
 */

const initial = useWorkspaceStore.getState();

const renderShell = () =>
  render(
    <WorkspaceShell
      tabs={<span>вкладки</span>}
      toolbar={<span>инструменты</span>}
      leftTitle="документ.pdf"
      left={<span>левая панель</span>}
      center={<span>чертёж</span>}
      rightTitle="Свойства области"
      right={<span>инспектор</span>}
      status={<span>статус</span>}
    />,
  );

describe('каркас рабочей области', () => {
  beforeEach(() => {
    useWorkspaceStore.setState(initial, true);
  });

  it('показывает все три ряда хрома и три колонки', () => {
    renderShell();

    for (const text of [
      'вкладки',
      'инструменты',
      'левая панель',
      'чертёж',
      'инспектор',
      'статус',
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it('центр принимает произвольное содержимое', () => {
    // Просмотрщик встанет сюда в промте 07, и раскладку менять не придётся.
    renderShell();

    expect(screen.getByRole('main')).toHaveTextContent('чертёж');
  });

  describe('сворачивание панелей', () => {
    it('свёрнутая левая панель прячет содержимое и предлагает развернуть', async () => {
      const user = userEvent.setup();
      useWorkspaceStore.setState({ leftCollapsed: true });
      renderShell();

      expect(screen.getByLabelText(/Панель документов.*свёрнута/)).toBeInTheDocument();
      expect(screen.queryByText('левая панель')).not.toBeInTheDocument();

      const expand = screen.getByTitle(/Развернуть/);

      expect(expand).toHaveAttribute('aria-expanded', 'false');

      await user.click(expand);
      expect(useWorkspaceStore.getState().leftCollapsed).toBe(false);
    });

    it('у свёрнутой панели нет разделителя — тянуть нечего', () => {
      useWorkspaceStore.setState({ leftCollapsed: true });
      renderShell();

      expect(screen.queryByLabelText('Ширина левой панели')).not.toBeInTheDocument();
      expect(screen.getByLabelText('Ширина панели свойств')).toBeInTheDocument();
    });
  });

  describe('разделитель', () => {
    it('объявляет пределы для программ чтения с экрана', () => {
      renderShell();

      const splitter = screen.getByLabelText('Ширина левой панели');

      expect(splitter).toHaveAttribute('role', 'separator');
      expect(splitter).toHaveAttribute('aria-valuemin', String(PANE_LIMITS.MIN_LEFT));
      expect(splitter).toHaveAttribute('aria-valuemax', String(PANE_LIMITS.MAX_LEFT));
    });

    it('стрелки меняют ширину панели', async () => {
      const user = userEvent.setup();
      renderShell();

      const splitter = screen.getByLabelText('Ширина левой панели');
      splitter.focus();
      await user.keyboard('{ArrowRight}');

      const width = useWorkspaceStore.getState().leftWidth;
      expect(width).not.toBeNull();
      expect(width).toBeGreaterThan(PANE_LIMITS.MIN_LEFT);
    });

    it('ширина не выходит за пределы', () => {
      const { setLeftWidth, setRightWidth } = useWorkspaceStore.getState();

      setLeftWidth(10_000);
      setRightWidth(0);

      expect(useWorkspaceStore.getState().leftWidth).toBe(PANE_LIMITS.MAX_LEFT);
      expect(useWorkspaceStore.getState().rightWidth).toBe(PANE_LIMITS.MIN_RIGHT);
    });
  });

  describe('состояние области', () => {
    it('видимость типов областей переключается', () => {
      const { toggleType } = useWorkspaceStore.getState();

      toggleType('stamp');
      expect(useWorkspaceStore.getState().hiddenTypes.has('stamp')).toBe(true);

      toggleType('stamp');
      expect(useWorkspaceStore.getState().hiddenTypes.has('stamp')).toBe(false);
    });

    it('слой распознавания включён по умолчанию', () => {
      expect(useWorkspaceStore.getState().overlayVisible).toBe(true);
    });
  });
});
