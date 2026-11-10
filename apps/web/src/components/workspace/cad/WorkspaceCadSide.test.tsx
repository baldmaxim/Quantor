import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { diagnostics } from '@/components/cad/viewer/fixtures';

const mocks = vi.hoisted(() => ({ detail: vi.fn() }));

vi.mock('@/components/cad/CadJobDetail', () => ({
  CadJobDetail: (props: { jobId: string; selectedPage: number | null }) => {
    mocks.detail(props);
    return <p>ход задания {props.jobId}</p>;
  },
}));
vi.mock('@/components/cad/viewer/CadRemarksPanel', () => ({
  CadRemarksPanel: () => <p>панель замечаний</p>,
}));
vi.mock('@/components/cad/viewer/CadFilesSection', () => ({
  CadFilesSection: () => <p>панель файлов</p>,
}));

import type { IWorkspaceCadSideProps } from './types';
import { WorkspaceCadSide } from './WorkspaceCadSide';

const JOB = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'j1',
  page: 0,
  view: 1,
  onSelectView: vi.fn(),
  onJobCreated: vi.fn(),
};

const VIEW: NonNullable<IWorkspaceCadSideProps['view']> = {
  diagnostics: diagnostics(),
  layers: {
    layers: ['WALLS'],
    visibleLayers: new Set([0]),
    onToggleLayer: vi.fn(),
    pdfOpacity: 0.4,
    onPdfOpacityChange: vi.fn(),
    pdfOpacityActive: true,
    cadShown: true,
    previewAvailable: true,
    pointCount: 6,
    cropAvailable: false,
    cropVisible: false,
    onCropChange: vi.fn(),
  },
  remarks: {} as never,
};

const mount = (patch: Partial<IWorkspaceCadSideProps> = {}) =>
  render(
    <WorkspaceCadSide
      state="ready"
      sheetLabel="1"
      loadError={null}
      onRetry={vi.fn()}
      job={JOB}
      viewLoading={false}
      viewError={null}
      view={VIEW}
      {...patch}
    />,
  );

describe('WorkspaceCadSide', () => {
  it('лист с результатом: пять разделов, открыт «Слои» с ползунком непрозрачности PDF', () => {
    mount();
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Слои',
      'Замечания',
      'Масштаб',
      'Файлы',
      'Задание',
    ]);
    expect(screen.getByRole('tab', { name: 'Слои' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Непрозрачность PDF')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'WALLS' })).toBeChecked();
  });

  it('раздел «Задание» показывает ход выбранного задания для листа', () => {
    mount();
    fireEvent.click(screen.getByRole('tab', { name: 'Задание' }));
    expect(screen.getByText('ход задания j1')).toBeVisible();
    expect(mocks.detail.mock.calls.at(-1)?.[0]).toMatchObject({ jobId: 'j1', selectedPage: 0 });
  });

  it('выбранный раздел остаётся при смене диагностики (переходе на другой лист)', () => {
    const view = mount();
    fireEvent.click(screen.getByRole('tab', { name: 'Файлы' }));
    view.rerender(
      <WorkspaceCadSide
        state="ready"
        sheetLabel="2"
        loadError={null}
        onRetry={vi.fn()}
        job={{ ...JOB, page: 1 }}
        viewLoading={false}
        viewError={null}
        view={{ ...VIEW, diagnostics: diagnostics({ page_index: 1 }) }}
      />,
    );
    expect(screen.getByRole('tab', { name: 'Файлы' })).toHaveAttribute('aria-selected', 'true');
  });

  it('задание есть, вида нет (идёт или отказ): только «Задание»', () => {
    mount({ view: null });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Задание']);
    expect(screen.getByText('ход задания j1')).toBeVisible();
  });

  it('вид читается: скелетон в разделе «Задание»', () => {
    mount({ view: null, viewLoading: true });
    expect(screen.getByRole('status', { name: 'Загрузка вида' })).toBeInTheDocument();
  });

  it('отказ чтения вида показан, задание остаётся доступным', () => {
    mount({ view: null, viewError: { code: 'CAD_JOB', text: 'не вышло' } });
    expect(screen.getByText('Результат CAD не загружен')).toBeInTheDocument();
    expect(screen.getByText('ход задания j1')).toBeInTheDocument();
  });

  it('лист не преобразовывался: подсказка, панели с разделами нет', () => {
    mount({ state: 'none', job: null, view: null });
    expect(screen.getByText('Лист не преобразовывался')).toBeInTheDocument();
    expect(screen.queryByRole('tab')).toBeNull();
  });

  it('лист не выбран', () => {
    mount({ state: 'no-sheet', job: null, view: null });
    expect(screen.getByText('Лист не выбран.')).toBeInTheDocument();
  });

  it('загрузка заданий и отказ с повтором', () => {
    const { unmount } = mount({ state: 'loading', job: null, view: null });
    expect(screen.getByRole('status', { name: 'Загрузка заданий CAD' })).toBeInTheDocument();
    unmount();

    const onRetry = vi.fn();
    mount({ state: 'error', job: null, view: null, loadError: 'нет связи', onRetry });
    expect(screen.getByRole('alert')).toHaveTextContent('нет связи');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
