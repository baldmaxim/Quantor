import type { CadJobRead } from '@quantor/api-client';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  features: { 'takeoff.manual': true } as Record<string, boolean>,
}));

vi.mock('@/lib/queries', () => ({
  useSheets: () => ({ data: { items: [{ id: 's', page_index: 2 }] } }),
  useFeatures: () => mocks.features,
}));

import { CadCalibrationMismatch } from './CadCalibrationMismatch';

const job = (code: string | null) =>
  ({
    pages: [
      {
        index: 2,
        legacy_pdf_page: 3,
        views: [
          {
            view: 1,
            status: 'ok',
            failure_code: code,
            failure_reason: 'Проверьте калибровку: 26%',
          },
        ],
      },
    ],
  }) as unknown as CadJobRead;

beforeEach(() => {
  mocks.features = { 'takeoff.manual': true };
});

describe('CadCalibrationMismatch', () => {
  it('calibration_mismatch: причина и ссылка на лист', () => {
    render(
      <CadCalibrationMismatch projectId="p" revisionId="r" job={job('calibration_mismatch')} />,
    );
    expect(screen.getByText('Проверьте калибровку: 26%')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Проверить калибровку' })).toHaveAttribute(
      'href',
      '/projects/p/workspace?revision=r&page=1',
    );
  });

  it('другого кода отказа блока нет', () => {
    const { container } = render(
      <CadCalibrationMismatch projectId="p" revisionId="r" job={job(null)} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('флаг выключен: вместо ссылки - пояснение', () => {
    mocks.features = {};
    render(
      <CadCalibrationMismatch projectId="p" revisionId="r" job={job('calibration_mismatch')} />,
    );
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText(/Калибровка недоступна/)).toBeInTheDocument();
  });
});
