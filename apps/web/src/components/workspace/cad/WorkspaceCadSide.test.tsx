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
vi.mock('@/components/cad/CadJobList', () => ({
  CadJobList: (props: { selectedJobId: string | null; onSelect: (id: string) => void }) => (
    <button type="button" onClick={() => props.onSelect('j9')}>
      список заданий, выбрано {props.selectedJobId ?? 'ничего'}
    </button>
  ),
}));
vi.mock('@/components/cad/CadResult', () => ({
  CadResult: (props: { attempt: number }) => <p>результат попытки {props.attempt}</p>,
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
  IWorkspaceCadSections,
  IWorkspaceCadSideProps,
  IWorkspaceCadZones,
} from './types';
import {
  WorkspaceCadSide,
  type IWorkspaceCadSideJobs,
  type IWorkspaceCadSidePipeline,
} from './WorkspaceCadSide';

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
  onCalibrate: vi.fn(),
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
  },
  remarks: {} as never,
};

const ZONES = {} as IWorkspaceCadZones;

const SECTIONS = (isSectionPage: boolean) =>
  ({
    status: 'ready',
    data: null,
    loadError: null,
    onReload: vi.fn(),
    pageIndex: 3,
    isSectionPage,
    starting: false,
    onStart: vi.fn(),
    deciding: false,
    onDecide: vi.fn(),
    actionError: null,
    activeLevelId: null,
    onSelectLevel: vi.fn(),
    markupVisible: true,
    onMarkupVisibleChange: vi.fn(),
    onOpenPage: vi.fn(),
  }) as IWorkspaceCadSections;

const mount = (
  patch: Partial<IWorkspaceCadSideProps> & IWorkspaceCadSideJobs & IWorkspaceCadSidePipeline = {},
) =>
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
  it('лист плана: вкладки «Разрезы» нет', () => {
    mount({ sections: SECTIONS(false) });
    expect(screen.queryByRole('tab', { name: 'Разрезы' })).toBeNull();
  });

  it('страница-разрез: «Разрезы» первая и открыта по умолчанию', () => {
    mount({ sections: SECTIONS(true) });
    const tabs = screen.getAllByRole('tab');
    expect(tabs[0]).toHaveTextContent('Разрезы');
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Слои' })).toBeInTheDocument();
  });

  it('переход с плана на страницу-разрез открывает «Разрезы», хотя раздел выбирали', () => {
    const onSideTabChange = vi.fn();
    const props = {
      state: 'ready' as const,
      sheetLabel: '1',
      loadError: null,
      onRetry: vi.fn(),
      job: JOB,
      convert: CONVERT,
      viewLoading: false,
      viewError: null,
      view: VIEW,
      onSideTabChange,
    };
    const plan = { ...SECTIONS(false), pageIndex: 10 };
    const section = { ...SECTIONS(true), pageIndex: 3 };
    const { rerender } = render(<WorkspaceCadSide {...props} sections={plan} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Файлы' }));
    rerender(<WorkspaceCadSide {...props} sections={section} />);
    expect(screen.getByRole('tab', { name: 'Разрезы' })).toHaveAttribute('aria-selected', 'true');
    expect(onSideTabChange).toHaveBeenLastCalledWith('sections');
  });

  it('страница-разрез: выбранная вручную вкладка не перебивается', () => {
    mount({ sections: SECTIONS(true), sideTab: 'files' });
    expect(screen.getByRole('tab', { name: 'Файлы' })).toHaveAttribute('aria-selected', 'true');
  });

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
    expect(screen.getByRole('checkbox', { name: 'Группа «Кладка и перегородки»' })).toBeChecked();
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

  it('задание листа упало: в «Задании» кнопки запуска нет, запуск - у бейджа в шапке', () => {
    mount({ view: null, job: { ...JOB, failed: true } });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Задание']);
    expect(screen.getByText('ход задания j1')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Преобразовать лист в CAD' })).toBeNull();
  });

  it('вкладки «Обработка» нет, по умолчанию открыты «Слои»', () => {
    mount();
    expect(screen.queryByRole('tab', { name: 'Обработка' })).toBeNull();
    expect(screen.getByRole('tab', { name: 'Слои' })).toHaveAttribute('aria-selected', 'true');
  });

  it('раздел, открытый снаружи, главнее выбора по умолчанию и сообщает о смене', () => {
    const onSideTabChange = vi.fn();
    mount({ sideTab: 'scale', onSideTabChange });
    expect(screen.getByRole('tab', { name: 'Масштаб' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: 'Файлы' }));
    expect(onSideTabChange).toHaveBeenCalledWith('files');
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

  it('лист не преобразовывался: подсказка, панели с разделами нет, запуска здесь нет', () => {
    mount({ state: 'none', job: null, view: null });
    expect(screen.getByText('Лист не преобразовывался')).toBeInTheDocument();
    expect(screen.queryByRole('tab')).toBeNull();
  });

  it('лист не преобразовывался: подсказка ведёт к статусу листа в шапке', () => {
    mount({ state: 'none', job: null, view: null });
    expect(screen.getByText(/нажмите статус листа вверху справа/)).toBeInTheDocument();
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

  it('«Задания» - последний раздел; список с выбранным заданием, выбор уходит наружу', () => {
    const onSelectJob = vi.fn();
    mount({
      jobs: { projectId: 'p1', revisionId: 'r1', selectedJobId: 'j7', onSelectJob },
    });
    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs.at(-1)).toBe('Задания');
    fireEvent.click(screen.getByRole('tab', { name: 'Задания' }));
    fireEvent.click(screen.getByText('список заданий, выбрано j7'));
    expect(onSelectJob).toHaveBeenCalledWith('j9');
  });

  it('лист без задания: «Задания» рядом с запуском преобразования, последним', () => {
    mount({
      state: 'none',
      job: null,
      view: null,
      zones: ZONES,
      jobs: { projectId: 'p1', revisionId: 'r1', selectedJobId: null, onSelectJob: vi.fn() },
    });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Задание',
      'Зоны',
      'Задания',
    ]);
  });

  it('без jobs раздела «Задания» нет', () => {
    mount();
    expect(screen.queryByRole('tab', { name: 'Задания' })).toBeNull();
  });
});
