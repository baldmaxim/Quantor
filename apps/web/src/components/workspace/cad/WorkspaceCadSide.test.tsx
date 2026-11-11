import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { diagnostics } from '@/components/cad/viewer/fixtures';

const mocks = vi.hoisted(() => ({ detail: vi.fn(), convert: vi.fn() }));

vi.mock('@/components/cad/CadJobDetail', () => ({
  CadJobDetail: (props: { jobId: string; selectedPage: number | null }) => {
    mocks.detail(props);
    return <p>ход задания {props.jobId}</p>;
  },
}));
vi.mock('@/components/cad/CadResult', () => ({
  CadResult: (props: { attempt: number }) => <p>результат попытки {props.attempt}</p>,
}));
vi.mock('./WorkspaceCadConvert', () => ({
  WorkspaceCadConvert: (props: { pageIndex: number; onJobCreated: (id: string, p: number[]) => void }) => {
    mocks.convert(props);
    return (
      <button type="button" onClick={() => props.onJobCreated('new', [props.pageIndex])}>
        Преобразовать лист в CAD
      </button>
    );
  },
}));
vi.mock('@/components/cad/viewer/CadRemarksPanel', () => ({
  CadRemarksPanel: () => <p>панель замечаний</p>,
}));
vi.mock('@/components/cad/viewer/CadZonesPanel', () => ({
  CadZonesPanel: () => <p>панель зон</p>,
}));
vi.mock('@/components/cad/viewer/CadFilesSection', () => ({
  CadFilesSection: () => <p>панель файлов</p>,
}));

import type { CadJobRead } from '@quantor/api-client';

import type {
  IWorkspaceCadConstructions,
  IWorkspaceCadSideProps,
  IWorkspaceCadZones,
} from './types';
import { WorkspaceCadSide } from './WorkspaceCadSide';

const DETAIL = { job_id: 'j1', attempt: 2, result_attempt: 1 } as CadJobRead;

const JOB = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'j1',
  detail: DETAIL,
  failed: false,
  page: 0,
  view: 1,
  onSelectView: vi.fn(),
};

const onConvertCreated = vi.fn();
const CONVERT: NonNullable<IWorkspaceCadSideProps['convert']> = {
  projectId: 'p1',
  revisionId: 'r1',
  sheetId: 's0',
  pageIndex: 0,
  calibrateHref: '/projects/p1/workspace?revision=r1&page=1',
  onJobCreated: onConvertCreated,
};

const VIEW: NonNullable<IWorkspaceCadSideProps['view']> = {
  diagnostics: diagnostics(),
  layers: {
    layers: ['WALLS'],
    visibleLayers: new Set([0]),
    onToggleLayer: vi.fn(),
    onSetLayersHidden: vi.fn(),
    pdfOpacity: 0.4,
    onPdfOpacityChange: vi.fn(),
    pdfOpacityActive: true,
    cadShown: true,
    previewAvailable: true,
    pointCount: 6,
    cropAvailable: false,
    cropVisible: false,
    onCropChange: vi.fn(),
    regionsVisible: false,
    onRegionsVisibleChange: vi.fn(),
    regionsAvailable: true,
  },
  remarks: {} as never,
};

const ZONES = {} as IWorkspaceCadZones;

const mount = (patch: Partial<IWorkspaceCadSideProps> = {}) =>
  render(
    <WorkspaceCadSide
      state="ready"
      sheetLabel="1"
      loadError={null}
      onRetry={vi.fn()}
      job={JOB}
      convert={CONVERT}
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
    expect(screen.getByRole('checkbox', { name: 'Группа «Стены»' })).toBeChecked();
  });

  it('«Масштаб» - человекочитаемая сводка без технических строк', () => {
    mount();
    fireEvent.click(screen.getByRole('tab', { name: 'Масштаб' }));
    expect(screen.getByTestId('cad-scale-summary')).toHaveTextContent('Масштаб 1:100');
    expect(screen.queryByText(/Независимые оси/)).toBeNull();
    expect(screen.queryByText(/Проверки движка/i)).toBeNull();
  });

  it('«Файлы» начинаются с результата попытки с результатом, затем файлы', () => {
    mount();
    fireEvent.click(screen.getByRole('tab', { name: 'Файлы' }));
    const result = screen.getByText('результат попытки 1');
    const files = screen.getByText('панель файлов');
    expect(result.compareDocumentPosition(files) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('«Задание» без блока «Действия» и без результата', () => {
    mount();
    fireEvent.click(screen.getByRole('tab', { name: 'Задание' }));
    expect(screen.queryByText('Действия')).toBeNull();
    expect(screen.queryByText(/Запустить по выбранным/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Преобразовать лист в CAD' })).toBeNull();
  });

  it('задание листа упало: в «Задании» кнопка «Преобразовать лист в CAD» создаёт новое', () => {
    mount({ view: null, job: { ...JOB, failed: true } });
    expect(screen.getByText('ход задания j1')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Преобразовать лист в CAD' }));
    expect(onConvertCreated).toHaveBeenCalledWith('new', [0]);
    expect(mocks.convert.mock.calls.at(-1)?.[0]).toMatchObject({ pageIndex: 0 });
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
        convert={CONVERT}
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

  it('лист не преобразовывался: подсказка и кнопка запуска, панели с разделами нет', () => {
    mount({ state: 'none', job: null, view: null });
    expect(screen.getByText('Лист не преобразовывался')).toBeInTheDocument();
    expect(screen.queryByRole('tab')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Преобразовать лист в CAD' }));
    expect(onConvertCreated).toHaveBeenCalledWith('new', [0]);
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

  it('с разделом зон: «Зоны» среди разделов листа с результатом, перед «Заданием»', () => {
    mount({ zones: ZONES });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Слои',
      'Замечания',
      'Масштаб',
      'Файлы',
      'Зоны',
      'Задание',
    ]);
    fireEvent.click(screen.getByRole('tab', { name: 'Зоны' }));
    expect(screen.getByText('панель зон')).toBeVisible();
  });

  it('лист без задания: зоны доступны рядом с запуском преобразования', () => {
    mount({ state: 'none', job: null, view: null, zones: ZONES });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Задание', 'Зоны']);
    expect(screen.getByText('Лист не преобразовывался')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Зоны' }));
    expect(screen.getByText('панель зон')).toBeVisible();
  });
  it('раздел «Конструкции» стоит перед «Заданием», его слой - в панели слоёв', () => {
    const constructions: IWorkspaceCadConstructions = {
      status: 'not-ready',
      data: null,
      notReadyText: 'Конструкции этого листа ещё не считались.',
      loadError: null,
      onReload: vi.fn(),
      calculating: false,
      actionError: null,
      onCompute: vi.fn(),
      levelsSaving: false,
      onSaveLevels: vi.fn(),
      activeGroup: null,
      onSelectGroup: vi.fn(),
    };
    mount({ constructions });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Слои',
      'Замечания',
      'Масштаб',
      'Файлы',
      'Конструкции',
      'Задание',
    ]);
    fireEvent.click(screen.getByRole('tab', { name: 'Конструкции' }));
    expect(screen.getByRole('button', { name: 'Посчитать конструкции' })).toBeVisible();
  });
});
