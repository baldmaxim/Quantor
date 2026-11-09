import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CadScaleSection } from './CadScaleSection';
import { scale } from './fixtures';

describe('CadScaleSection: калибровка человека', () => {
  it('показывает источник, 1:N, мм/pt, отклонение, статус и причину', () => {
    render(
      <CadScaleSection
        scale={scale({
          status: 'needs_review',
          passed: false,
          source: 'operator_calibration',
          operator_mm_per_pt: 70.5556,
          mm_per_pdf_point: 70.5556,
          dimension_mm_per_pt: 68.9,
          deviation: 0.023,
          reason: 'Отклонение 2,3% выше допуска проверки',
          hold_reasons: [],
        })}
      />,
    );
    const block = screen.getByTestId('cad-scale-source');
    expect(block).toHaveTextContent('Калибровка человека');
    expect(block).toHaveTextContent('требует проверки');
    expect(block).toHaveTextContent('1:200');
    expect(block).toHaveTextContent('70,5556');
    expect(block).toHaveTextContent('68,9');
    expect(block).toHaveTextContent(/2,3\s*%/);
    expect(block).toHaveTextContent('Отклонение 2,3% выше допуска проверки');
  });

  it('отклонённая калибровка помечена «отклонена»', () => {
    render(
      <CadScaleSection
        scale={scale({
          status: 'failed',
          passed: false,
          source: 'operator_calibration',
          deviation: 0.26,
          reason: 'Проверьте калибровку',
          hold_reasons: ['Проверьте калибровку'],
        })}
      />,
    );
    expect(screen.getByTestId('cad-scale-source')).toHaveTextContent('отклонена');
  });

  it('без источника блока калибровки нет', () => {
    render(<CadScaleSection scale={scale()} />);
    expect(screen.queryByTestId('cad-scale-source')).toBeNull();
  });
});
