import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CadFloor3dLegend } from './CadFloor3dLegend';

describe('легенда 3D: окна', () => {
  it('без окон записей окон нет', () => {
    render(<CadFloor3dLegend />);
    expect(screen.queryByText('Окно по фасаду')).toBeNull();
    expect(screen.queryByText('Подоконная часть')).toBeNull();
  });

  it('с окнами - окно и подоконная часть; кандидат - только когда есть', () => {
    const { rerender } = render(<CadFloor3dLegend hasWindows />);
    expect(screen.getByText('Окно по фасаду')).toBeInTheDocument();
    expect(screen.getByText('Подоконная часть')).toBeInTheDocument();
    expect(screen.queryByText(/Окно — кандидат/)).toBeNull();
    rerender(<CadFloor3dLegend hasWindows hasCandidateWindows />);
    expect(screen.getByText('Окно — кандидат (вид фасада не принят)')).toBeInTheDocument();
  });
});
