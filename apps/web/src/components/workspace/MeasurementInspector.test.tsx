import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MeasurementInspector } from './MeasurementInspector';
import type {
  MeasurementQuantityRead,
  MeasurementRead,
  ScaleCalibrationRead,
  TakeoffItemRead,
} from '@quantor/api-client';

/**
 * Показ величины.
 *
 * Проверяется не вёрстка, а то, что нельзя увидеть глазами на одном примере: недоступная
 * величина остаётся прочерком и никогда не превращается в ноль. Ноль в смете выглядит
 * посчитанным, а прочерк виден сразу.
 */

const ITEM: TakeoffItemRead = {
  id: 'item-1',
  project_id: 'p1',
  name: 'Стены',
  code: null,
  geometry_type: 'line',
  display_unit: 'm',
  color_key: 'accent',
  ordinal: 0,
  archived_at: null,
  created_by: null,
  created_at: '2026-09-09T00:00:00Z',
  updated_at: '2026-09-09T00:00:00Z',
};

const MEASUREMENT: MeasurementRead = {
  id: 'm-1',
  takeoff_item_id: 'item-1',
  sheet_id: 's-1',
  geometry_type: 'line',
  points: [
    [0, 0.5],
    [1, 0.5],
  ],
  source: 'manual',
  scale_calibration_id: 'c-1',
  version: 1,
  created_by: null,
  created_at: '2026-09-09T00:00:00Z',
  updated_at: '2026-09-09T00:00:00Z',
};

const CALIBRATION = {
  id: 'c-1',
  sheet_id: 's-1',
  mm_per_pt: '10.000000000000',
} as ScaleCalibrationRead;

const READY: MeasurementQuantityRead = {
  measurement_id: 'm-1',
  takeoff_item_id: 'item-1',
  state: 'ready',
  value: '12.5',
  unit: 'm',
  canonical_value: '12500',
  canonical_unit: 'mm',
  rule_key: 'length.v1',
  rule_version: 'v1',
  page_geometry_fingerprint: 'a'.repeat(64),
  scale_calibration_id: 'c-1',
  input_fingerprint: 'b'.repeat(64),
  verification_state: 'unverified',
};

const view = (quantity: MeasurementQuantityRead | null) =>
  render(
    <MeasurementInspector
      measurement={MEASUREMENT}
      item={ITEM}
      calibration={CALIBRATION}
      quantity={quantity}
      sheetLabel="1"
      canEdit
      onDelete={vi.fn()}
    />,
  );

describe('свойства измерения', () => {
  it('показывает величину, посчитанную сервером', () => {
    view(READY);

    expect(screen.getByText(/12,5\s*м/)).toBeInTheDocument();
  });

  it('показывает правило с версией', () => {
    // Без правила величину нечем объяснить через полгода: «12,5 м» само по себе
    // не говорит, чем и по какой геометрии оно посчитано.
    view(READY);

    expect(screen.getByText('length.v1')).toBeInTheDocument();
  });

  it('без масштаба показывает отсутствие основания, а не ноль', () => {
    view({ ...READY, state: 'unavailable_no_scale', value: null, canonical_value: null });

    expect(screen.getByText('нет масштаба')).toBeInTheDocument();
    expect(screen.queryByText(/^0\b/)).not.toBeInTheDocument();
  });

  it('без геометрии страницы говорит именно об этом', () => {
    // Две разные причины недоступности требуют разных действий: задать масштаб или
    // дождаться извлечения геометрии.
    view({ ...READY, state: 'unavailable_no_geometry', value: null, canonical_value: null });

    expect(screen.getByText('нет геометрии')).toBeInTheDocument();
  });

  it('пока ответ не пришёл, числа не выдумывает', () => {
    view(null);

    expect(screen.getByText('…')).toBeInTheDocument();
  });
});
