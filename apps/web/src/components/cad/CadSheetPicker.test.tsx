import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  calibrations: new Map<number, string>(),
  features: { 'takeoff.manual': true } as Record<string, boolean>,
}));

vi.mock('@/lib/queries', () => ({
  useSheets: () => ({
    isPending: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
    data: {
      total: 2,
      items: [
        { id: 's0', page_index: 0, page_label: '1' },
        { id: 's1', page_index: 1, page_label: '2' },
      ],
    },
  }),
  useFeatures: () => mocks.features,
}));
vi.mock('@/lib/cad/sheet-queries', () => ({
  useSheetCalibrationStates: () => mocks.calibrations,
}));
vi.mock('@/lib/cad/queries', () => ({
  useCreateCadJob: () => ({ mutate: mocks.mutate, isPending: false }),
}));

import { CadSheetPicker } from './CadSheetPicker';

const mount = (onJobCreated = vi.fn()) =>
  render(<CadSheetPicker projectId="p" revisionId="r" onJobCreated={onJobCreated} />);

const launchButton = () => screen.getByRole('button', { name: /Запустить преобразование/ });

beforeEach(() => {
  mocks.mutate.mockReset();
  mocks.features = { 'takeoff.manual': true };
  mocks.calibrations = new Map([
    [0, 'calibrated'],
    [1, 'missing'],
  ]);
});

describe('CadSheetPicker', () => {
  it('по умолчанию ничего не выбрано, запуск неактивен', () => {
    mount();
    expect(screen.getByRole('checkbox', { name: /Стр. 1/ })).not.toBeChecked();
    expect(launchButton()).toBeDisabled();
  });

  it('откалиброванный лист запускается с его индексом', () => {
    mount();
    fireEvent.click(screen.getByRole('checkbox', { name: /Стр. 1/ }));
    expect(launchButton()).toBeEnabled();
    fireEvent.click(launchButton());
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
    expect(mocks.mutate.mock.calls[0]?.[0]).toEqual({ pages: [0] });
  });

  it('лист без калибровки: метка, ссылка на просмотрщик и закрытый запуск', () => {
    mount();
    expect(screen.getByText('Нет калибровки')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Откалибровать' })).toHaveAttribute(
      'href',
      '/projects/p/workspace?revision=r&page=2',
    );
    fireEvent.click(screen.getByRole('checkbox', { name: /Стр. 1/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /Стр. 2/ }));
    expect(launchButton()).toBeDisabled();
    expect(screen.getByText(/Нет калибровки: Стр. 2/)).toBeInTheDocument();
  });

  it('флаг ручного обмера выключен: вместо ссылки - пояснение', () => {
    mocks.features = {};
    mocks.calibrations = new Map([[1, 'missing']]);
    mount();
    expect(screen.queryByRole('link', { name: 'Откалибровать' })).toBeNull();
    expect(
      screen.getAllByText(/Калибровка недоступна: включите в пространстве флаг/).length,
    ).toBeGreaterThan(0);
  });

  it('ответ 409 показывает страницы и блокирует их', () => {
    mocks.calibrations = new Map([
      [0, 'unknown'],
      [1, 'calibrated'],
    ]);
    mount();
    fireEvent.click(screen.getByRole('checkbox', { name: /Стр. 1/ }));
    fireEvent.click(launchButton());
    const options = mocks.mutate.mock.calls[0]?.[1] as { onError: (error: unknown) => void };
    act(() => {
      options.onError({ detail: { code: 'CAD_CALIBRATION_REQUIRED', issue: { pages: '0' } } });
    });
    expect(screen.getByRole('alert')).toHaveTextContent('стр. 1');
    expect(screen.getByText('Нет калибровки')).toBeInTheDocument();
    expect(launchButton()).toBeDisabled();
  });
});
