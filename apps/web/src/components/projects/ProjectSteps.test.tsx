import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as queries from '@/lib/queries';

import { ProjectNextStep, ProjectSteps } from './ProjectSteps';

vi.mock('@/lib/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof queries>()),
  useFeatures: vi.fn(),
}));

describe('путь проекта', () => {
  beforeEach(() => {
    vi.mocked(queries.useFeatures).mockReturnValue({
      'cad.export': true,
      'project.consistency': true,
      'model.import': true,
      'tender.exchange': true,
    });
  });

  it('шаги с номерами по порядку, шаги этой страницы отмечены, прочие разделы - ссылками', () => {
    render(<ProjectSteps projectId="p1" current={['documents', 'cad']} />);
    const nav = screen.getByRole('navigation', { name: 'Путь проекта' });
    const links = within(nav).getAllByRole('link');
    expect(links[0]).toHaveTextContent('1Документызагрузите PDF и IFC');
    expect(within(nav).getByRole('link', { name: /Здание/ })).toHaveAttribute(
      'href',
      '/projects/p1/building3d',
    );
    expect(within(nav).getByRole('link', { name: /Документы/ })).toHaveAttribute(
      'aria-current',
      'step',
    );
    expect(within(nav).getByRole('link', { name: /CAD по листам/ })).toHaveAttribute(
      'aria-current',
      'step',
    );
    expect(within(nav).getByRole('link', { name: /Здание/ })).not.toHaveAttribute('aria-current');
    expect(within(nav).getByRole('link', { name: 'Каркас здания' })).toHaveAttribute(
      'href',
      '/projects/p1/frame',
    );
  });

  it('«Дальше» на странице шага ведёт на следующий шаг', () => {
    render(<ProjectNextStep projectId="p1" current="building" />);
    expect(screen.getByRole('link', { name: 'Дальше: Модель здания →' })).toHaveAttribute(
      'href',
      '/projects/p1/model',
    );
  });

  it('последний шаг - кнопки «Дальше» нет', () => {
    const { container } = render(<ProjectNextStep projectId="p1" current="access" />);
    expect(container).toBeEmptyDOMElement();
  });
});
