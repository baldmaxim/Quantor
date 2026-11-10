import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  calibration: { current: 'calibrated' as string },
  features: { current: { 'takeoff.manual': true } as Record<string, boolean> },
  states: vi.fn(),
}));

vi.mock('@/lib/queries', () => ({ useFeatures: () => mocks.features.current }));
vi.mock('@/lib/cad/sheet-queries', () => ({
  useSheetCalibrationStates: (sheets: readonly { page_index: number }[], enabled: boolean) => {
    mocks.states(sheets, enabled);
    return new Map(sheets.map((sheet) => [sheet.page_index, mocks.calibration.current]));
  },
}));
vi.mock('@/lib/cad/queries', () => ({
  useCreateCadJob: () => ({ mutate: mocks.mutate, isPending: false }),
}));

import { WorkspaceCadConvert } from './WorkspaceCadConvert';

const HREF = '/projects/p/workspace?revision=r&page=4';

const mount = (onJobCreated = vi.fn()) => {
  render(
    <WorkspaceCadConvert
      projectId="p"
      revisionId="r"
      sheetId="s3"
      pageIndex={3}
      calibrateHref={HREF}
      onJobCreated={onJobCreated}
    />,
  );
  return onJobCreated;
};

const button = () => screen.getByRole('button', { name: 'Преобразовать лист в CAD' });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.calibration.current = 'calibrated';
  mocks.features.current = { 'takeoff.manual': true };
});

describe('WorkspaceCadConvert', () => {
  it('создаёт задание на одну страницу листа и сообщает о нём', () => {
    const onJobCreated = mount();
    fireEvent.click(button());
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
    expect(mocks.mutate.mock.calls[0]?.[0]).toEqual({ pages: [3] });
    const options = mocks.mutate.mock.calls[0]?.[1] as { onSuccess: (job: unknown) => void };
    act(() => options.onSuccess({ job_id: 'new', requested_pages: [3] }));
    expect(onJobCreated).toHaveBeenCalledWith('new', [3]);
  });

  it('калибровка читается только у этого листа', () => {
    mount();
    const [sheets, enabled] = mocks.states.mock.calls.at(-1) as [{ id: string; page_index: number }[], boolean];
    expect(sheets).toEqual([{ id: 's3', page_index: 3 }]);
    expect(enabled).toBe(true);
  });

  it('нет калибровки: метка и ссылка «Откалибровать», запуск закрыт', () => {
    mocks.calibration.current = 'missing';
    mount();
    expect(screen.getByText('Нет калибровки')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Откалибровать' })).toHaveAttribute('href', HREF);
    expect(button()).toBeDisabled();
    fireEvent.click(button());
    expect(mocks.mutate).not.toHaveBeenCalled();
  });

  it('флаг ручного обмера выключен: вместо ссылки - пояснение', () => {
    mocks.features.current = {};
    mocks.calibration.current = 'missing';
    mount();
    expect(screen.queryByRole('link', { name: 'Откалибровать' })).toBeNull();
    expect(screen.getByText(/Калибровка недоступна: включите в пространстве флаг/)).toBeInTheDocument();
  });

  it('калибровка проверяется - запуск закрыт; статус не прочитан - решает сервер', () => {
    mocks.calibration.current = 'loading';
    const { unmount } = render(
      <WorkspaceCadConvert projectId="p" revisionId="r" sheetId="s3" pageIndex={3} calibrateHref={HREF} onJobCreated={vi.fn()} />,
    );
    expect(button()).toBeDisabled();
    unmount();

    mocks.calibration.current = 'unknown';
    mount();
    expect(button()).toBeEnabled();
  });

  it('ответ 409 по этой странице: метка, ссылка и закрытый запуск', () => {
    mocks.calibration.current = 'unknown';
    mount();
    fireEvent.click(button());
    const options = mocks.mutate.mock.calls[0]?.[1] as { onError: (error: unknown) => void };
    act(() => {
      options.onError({ detail: { code: 'CAD_CALIBRATION_REQUIRED', issue: { pages: '3' } } });
    });
    expect(screen.getByRole('alert')).toHaveTextContent('стр. 4');
    expect(screen.getByText('Нет калибровки')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Откалибровать' })).toBeInTheDocument();
    expect(button()).toBeDisabled();
  });

  it('иной отказ: текст ошибки, запуск остаётся доступным', () => {
    mocks.calibration.current = 'unknown';
    mount();
    fireEvent.click(button());
    const options = mocks.mutate.mock.calls[0]?.[1] as { onError: (error: unknown) => void };
    act(() => options.onError({ detail: { code: 'CAD_OTHER' } }));
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('Нет калибровки')).toBeNull();
    expect(button()).toBeEnabled();
  });
});
