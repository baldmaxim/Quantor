import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CadBulkLaunchBar, type ICadBulkLaunchBarProps } from './CadBulkLaunchBar';

const bar = (overrides: Partial<ICadBulkLaunchBarProps> = {}) => {
  const props: ICadBulkLaunchBarProps = {
    plansCount: 5,
    withoutCadCount: 3,
    launchableCount: 3,
    selectedCount: 0,
    running: false,
    total: 0,
    finished: 0,
    failures: [],
    onToggleAll: vi.fn(),
    onLaunch: vi.fn(),
    onStop: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<CadBulkLaunchBar {...props} />) };
};

describe('панель массового запуска', () => {
  it('сводка и кнопка с числом выбранных; пока ничего не выбрано - неактивна', () => {
    bar();
    expect(screen.getByText('Планов: 5 · без CAD: 3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Запустить конвейер (0)' })).toBeDisabled();
  });

  it('частичный выбор: чекбокс неопределённый, «выбрать все» выбирает все доступные', async () => {
    const user = userEvent.setup();
    const { props } = bar({ selectedCount: 1 });
    const all = screen.getByRole<HTMLInputElement>('checkbox', { name: 'Выбрать все доступные' });
    expect(all.indeterminate).toBe(true);
    expect(all.checked).toBe(false);

    await user.click(all);
    expect(props.onToggleAll).toHaveBeenCalledWith(true);
  });

  it('выбраны все доступные: чекбокс отмечен, повторный щелчок снимает выбор', async () => {
    const user = userEvent.setup();
    const { props } = bar({ selectedCount: 3 });
    const all = screen.getByRole<HTMLInputElement>('checkbox', { name: 'Выбрать все доступные' });
    expect(all.checked).toBe(true);
    expect(all.indeterminate).toBe(false);

    await user.click(all);
    expect(props.onToggleAll).toHaveBeenCalledWith(false);
  });

  it('доступных листов нет: «выбрать все» неактивен', () => {
    bar({ launchableCount: 0 });
    expect(screen.getByRole('checkbox', { name: 'Выбрать все доступные' })).toBeDisabled();
  });

  it('запуск: кнопка вызывает обработчик', async () => {
    const user = userEvent.setup();
    const { props } = bar({ selectedCount: 2 });
    await user.click(screen.getByRole('button', { name: 'Запустить конвейер (2)' }));
    expect(props.onLaunch).toHaveBeenCalledTimes(1);
  });

  it('идёт партия: прогресс, «Остановить», выбор заблокирован', async () => {
    const user = userEvent.setup();
    const { props } = bar({ selectedCount: 3, running: true, total: 3, finished: 1 });
    expect(screen.getByText('Листов: готово 1 из 3, идёт 2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Запустить конвейер/ })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Выбрать все доступные' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Остановить' }));
    expect(props.onStop).toHaveBeenCalledTimes(1);
  });

  it('партия закончена: итог и ошибки по листам', () => {
    bar({
      total: 3,
      finished: 3,
      failures: [{ pageIndex: 1, label: 'Лист 2', message: 'Сервер недоступен' }],
    });
    expect(screen.getByText('Листов: готово 3 из 3')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Листов с ошибкой: 1');
    expect(screen.getByText('Лист 2: Сервер недоступен')).toBeInTheDocument();
  });
});
