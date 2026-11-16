import type { CadZonesSheetSummaryRead } from '@quantor/api-client';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CadZonesQuality, type ICadZonesQualityProps } from './CadZonesQuality';
import { zoneFixture } from './zoneModeTestUtils';

const acceptMutate = vi.fn();
const removeMutate = vi.fn();
const summaryState: { data: CadZonesSheetSummaryRead | undefined; isError: boolean } = {
  data: undefined,
  isError: false,
};

vi.mock('@/lib/cad/zones-quality-queries', () => ({
  useCadZonesSummary: () => summaryState,
  useAcceptCadZone: () => ({ mutate: acceptMutate, isPending: false, error: null }),
  useDeleteCadZonesOfSheet: () => ({ mutate: removeMutate, isPending: false, error: null }),
}));

const summary = (patch: Partial<CadZonesSheetSummaryRead> = {}): CadZonesSheetSummaryRead => ({
  revision_id: 'r1',
  page_index: 0,
  ok: 3,
  review: 1,
  failed: 1,
  auto: 5,
  human: 0,
  unknown: 0,
  generator_versions: ['cad_mep.v16.6'],
  apartments_compared: 4,
  apartments_area_m2: 68.9,
  apartments_expl_area_m2: 53.1,
  apartments_delta_percent: 29.8,
  unmatched_marks: [
    {
      room_mark: '3-3.4',
      name: 'Лестничная клетка',
      expl_area_m2: 15.1,
      reason: 'полигон не построен',
    },
  ],
  recreate_allowed: true,
  ...patch,
});

const zones = [
  zoneFixture({ id: 'ok', name: 'Спальня' }),
  zoneFixture({
    id: 'rev',
    name: 'Кухня',
    quality_status: 'review',
    quality_reason: 'площадь 11,50 м² против 10,00 м² по экспликации (+15,0 %): допуск ±10 %',
  }),
  zoneFixture({
    id: 'bad',
    name: 'Гостиная',
    quality_status: 'failed',
    quality_reason: 'больше экспликации в 1,5 раза',
  }),
];

const mount = (patch: Partial<ICadZonesQualityProps> = {}) => {
  const props: ICadZonesQualityProps = {
    projectId: 'p1',
    revisionId: 'r1',
    pageIndex: 0,
    load: true,
    zones,
    activeId: null,
    onActivate: vi.fn(),
    recreate: { onStart: vi.fn(), starting: false },
    ...patch,
  };
  return { props, ...render(<CadZonesQuality {...props} />) };
};

describe('CadZonesQuality', () => {
  beforeEach(() => {
    acceptMutate.mockReset();
    removeMutate.mockReset();
    summaryState.data = summary();
    summaryState.isError = false;
  });

  it('лист без зон: блока нет', () => {
    const { container } = mount({ zones: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it('сводка: итоги сверки, сумма по квартирам против экспликации, марки без зоны', async () => {
    const user = userEvent.setup();
    mount();
    expect(screen.getByText('в допуске: 3')).toBeInTheDocument();
    expect(screen.getByText('на проверку: 1')).toBeInTheDocument();
    expect(screen.getByText('отклонено: 1')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Квартиры: 68,9 м² против 53,1 м² по экспликации (+29,8 %), зон в сверке: 4',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Авто: 5 · человек: 0 · cad_mep.v16.6')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Марки без зоны: 1' }));
    expect(
      screen.getByText('3-3.4 · Лестничная клетка · 15,1 м² · полигон не построен'),
    ).toBeInTheDocument();
  });

  it('зоны вне допуска: отклонённая первой, причина, выделение на листе и принятие', async () => {
    const user = userEvent.setup();
    const { props } = mount();
    const items = within(screen.getByRole('list', { name: 'Зоны вне допуска' })).getAllByRole(
      'listitem',
    );
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('отклонена');
    expect(items[0]).toHaveTextContent('больше экспликации в 1,5 раза');
    expect(items[1]).toHaveTextContent('на проверку');

    await user.click(within(items[0] as HTMLElement).getByRole('button', { pressed: false }));
    expect(props.onActivate).toHaveBeenCalledWith('bad');
    await user.click(screen.getByRole('button', { name: /Принять зону:.*Гостиная/ }));
    expect(acceptMutate).toHaveBeenCalledWith('bad');
  });

  it('массовое удаление - только после подтверждения: «только авто» и «все»', async () => {
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByRole('button', { name: 'Удалить авто-зоны' }));
    expect(removeMutate).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Удалить авто-зоны' }));
    expect(removeMutate).toHaveBeenCalledWith('auto');

    await user.click(screen.getByRole('button', { name: 'Удалить все зоны' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отмена' }));
    expect(removeMutate).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Удалить все зоны' }));
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить все зоны' }),
    );
    expect(removeMutate).toHaveBeenLastCalledWith('all');
  });

  it('пересоздание авто-зон: только когда все зоны листа авто, с подтверждением', async () => {
    const user = userEvent.setup();
    const { props } = mount();
    await user.click(screen.getByRole('button', { name: 'Разметить заново' }));
    expect(props.recreate?.onStart).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Разметить заново' }),
    );
    expect(props.recreate?.onStart).toHaveBeenCalledTimes(1);
  });

  it('на листе есть зоны человека: пересоздания и удаления авто-зон нет', () => {
    summaryState.data = summary({ recreate_allowed: false, auto: 0, human: 3 });
    mount();
    expect(screen.queryByRole('button', { name: 'Разметить заново' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Удалить авто-зоны' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Удалить все зоны' })).toBeInTheDocument();
  });
});
