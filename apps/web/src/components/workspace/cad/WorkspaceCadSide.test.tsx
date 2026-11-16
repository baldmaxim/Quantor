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
vi.mock('@/components/cad/mep/CadMepPanel', () => ({
  CadMepPanel: (props: { risers?: ReactNode }) => (
    <div>
      <p>панель трасс</p>
      {props.risers}
    </div>
  ),
}));
vi.mock('@/components/cad/risers/CadRisersPanel', () => ({
  CadRisersPanel: (props: { parent: { jobId: string } }) => <p>реестр стояков {props.parent.jobId}</p>,
}));
vi.mock('./CadStylePanel', () => ({ CadStylePanel: () => <p>панель профиля</p> }));
// Отделка читает сервер; её раздел проверяет WorkspaceCadSideFinishes.test.tsx.
vi.mock('@/components/cad/finishes/CadFinishPanel', () => ({
  CadFinishPanel: () => <p>панель отделки</p>,
}));

import type { CadJobRead } from '@quantor/api-client';
import type { ReactNode } from 'react';

import type {
  IWorkspaceCadConstructions,
  IWorkspaceCadFacades,
  IWorkspaceCadMep,
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

const FACADES = {
  status: 'ready',
  data: null,
  loadError: null,
  onReload: vi.fn(),
  starting: false,
  onStart: vi.fn(),
  deciding: false,
  onDecide: vi.fn(),
  actionError: null,
  activeViewId: null,
  onSelectView: vi.fn(),
  onPanelShown: vi.fn(),
  onOpenPage: vi.fn(),
} as IWorkspaceCadFacades;

const MEP = { parent: { jobId: 'j1' } } as IWorkspaceCadMep;

const CONSTRUCTIONS: IWorkspaceCadConstructions = {
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

const JOBS = (onSelectJob = vi.fn(), selectedJobId: string | null = 'j7') => ({
  projectId: 'p1',
  revisionId: 'r1',
  selectedJobId,
  onSelectJob,
});

const tabNames = () => screen.getAllByRole('tab').map((tab) => tab.textContent);
const openSheet = () => fireEvent.click(screen.getByRole('tab', { name: 'Лист' }));
/** Сворачиваемый блок раздела «Лист» по заголовку. */
const fold = (title: string) => {
  const details = screen.getByText(title).closest('details');
  if (details === null) throw new Error(`Блок «${title}» не сворачиваемый`);
  return details;
};

describe('WorkspaceCadSide', () => {
  it('«Фасады»: вкладка есть при переданном разделе и скрыта без него', () => {
    mount({ facades: FACADES });
    expect(screen.getByRole('tab', { name: 'Фасады' })).toBeInTheDocument();
  });

  it('без раздела (флаг cad.export выключен) вкладки «Фасады» нет', () => {
    mount();
    expect(screen.queryByRole('tab', { name: 'Фасады' })).toBeNull();
  });

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
    fireEvent.click(screen.getByRole('tab', { name: 'Замечания' }));
    rerender(<WorkspaceCadSide {...props} sections={section} />);
    expect(screen.getByRole('tab', { name: 'Разрезы' })).toHaveAttribute('aria-selected', 'true');
    expect(onSideTabChange).toHaveBeenLastCalledWith('sections');
  });

  it('страница-разрез: выбранная вручную вкладка не перебивается', () => {
    mount({ sections: SECTIONS(true), sideTab: 'remarks' });
    expect(screen.getByRole('tab', { name: 'Замечания' })).toHaveAttribute('aria-selected', 'true');
  });

  it('страница-разрез без вида: «Разрезы» открыты, «Лист» последний', () => {
    mount({ sections: SECTIONS(true), view: null, zones: ZONES });
    expect(tabNames()).toEqual(['Разрезы', 'Зоны', 'Лист']);
    expect(screen.getByRole('tab', { name: 'Разрезы' })).toHaveAttribute('aria-selected', 'true');
  });

  it('лист с результатом: три раздела, открыт «Слои» с ползунком непрозрачности PDF', () => {
    mount();
    expect(tabNames()).toEqual(['Слои', 'Замечания', 'Лист']);
    expect(screen.getByRole('tab', { name: 'Слои' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Непрозрачность PDF')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'WALLS' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Группа «Кладка и перегородки»' })).toBeChecked();
  });

  it('полный состав: девять разделов в едином порядке, «Лист» последний', () => {
    mount({
      sections: SECTIONS(true),
      zones: ZONES,
      constructions: CONSTRUCTIONS,
      finishes: { projectId: 'p1', revisionId: null, pageIndex: null, load: false },
      view: { ...VIEW, mep: MEP },
      facades: FACADES,
      style: {} as NonNullable<IWorkspaceCadSideProps['style']>,
      jobs: JOBS(),
    });
    expect(tabNames()).toEqual([
      'Разрезы',
      'Слои',
      'Зоны',
      'Конструкции',
      'Отделка',
      'Трассы',
      'Фасады',
      'Замечания',
      'Лист',
    ]);
  });

  it('прежних вкладок «Масштаб», «Файлы», «Задание», «Задания», «Стояки», «Профиль оформления» нет', () => {
    mount({
      view: { ...VIEW, mep: MEP },
      style: {} as NonNullable<IWorkspaceCadSideProps['style']>,
      jobs: JOBS(),
    });
    ['Масштаб', 'Файлы', 'Задание', 'Задания', 'Стояки', 'Профиль оформления'].forEach((name) =>
      expect(screen.queryByRole('tab', { name })).toBeNull(),
    );
  });

  it('«Лист»: масштаб - человекочитаемая сводка без технических строк', () => {
    mount();
    openSheet();
    expect(screen.getByTestId('cad-scale-summary')).toBeVisible();
    expect(screen.getByTestId('cad-scale-summary')).toHaveTextContent('Масштаб 1:100');
    expect(screen.queryByText(/Независимые оси/)).toBeNull();
    expect(screen.queryByText(/Проверки движка/i)).toBeNull();
  });

  it('«Лист»: после масштаба результат попытки с результатом, затем файлы, затем ход', () => {
    mount();
    openSheet();
    const order = [
      screen.getByTestId('cad-scale-summary'),
      screen.getByText('результат попытки 1'),
      screen.getByText('панель файлов'),
      screen.getByText('ход задания j1'),
    ];
    order.slice(1).forEach((node, index) => {
      const before = order[index];
      expect(before).toBeDefined();
      expect(
        (before as HTMLElement).compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });
    expect(screen.getByText('результат попытки 1')).toBeVisible();
    expect(screen.getByText('панель файлов')).toBeVisible();
  });

  it('«Лист» без блока «Действия» и без запуска преобразования', () => {
    mount();
    openSheet();
    expect(screen.queryByText('Действия')).toBeNull();
    expect(screen.queryByText(/Запустить по выбранным/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Преобразовать лист в CAD' })).toBeNull();
  });

  it('«Лист» с видом: ход, профиль и задания документа свёрнуты, но смонтированы', () => {
    mount({ style: {} as NonNullable<IWorkspaceCadSideProps['style']>, jobs: JOBS() });
    openSheet();
    ['Ход преобразования', 'Профиль оформления', 'Задания документа'].forEach((title) =>
      expect(fold(title)).not.toHaveAttribute('open'),
    );
    expect(fold('Ход преобразования')).toHaveTextContent('ход задания j1');
    expect(fold('Профиль оформления')).toHaveTextContent('панель профиля');
    expect(fold('Задания документа')).toHaveTextContent('список заданий, выбрано j7');
  });

  it('«Трассы»: реестр стояков передан внутрь раздела', () => {
    mount({ view: { ...VIEW, mep: MEP } });
    expect(tabNames()).toEqual(['Слои', 'Трассы', 'Замечания', 'Лист']);
    fireEvent.click(screen.getByRole('tab', { name: 'Трассы' }));
    expect(screen.getByText('панель трасс')).toBeVisible();
    expect(screen.getByText('реестр стояков j1')).toBeInTheDocument();
  });

  it('задание листа упало: в «Листе» кнопки запуска нет, запуск - у бейджа в шапке', () => {
    mount({ view: null, job: { ...JOB, failed: true } });
    expect(tabNames()).toEqual(['Лист']);
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
    mount({ sideTab: 'remarks', onSideTabChange });
    expect(screen.getByRole('tab', { name: 'Замечания' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: 'Лист' }));
    expect(onSideTabChange).toHaveBeenCalledWith('job');
  });

  it('окно «Обработка» открывает «Трассы» и «Конструкции» по их id', () => {
    const { unmount } = mount({ view: { ...VIEW, mep: MEP }, sideTab: 'mep' });
    expect(screen.getByRole('tab', { name: 'Трассы' })).toHaveAttribute('aria-selected', 'true');
    unmount();
    mount({ constructions: CONSTRUCTIONS, sideTab: 'constructions' });
    expect(screen.getByRole('tab', { name: 'Конструкции' })).toHaveAttribute('aria-selected', 'true');
  });

  it('неизвестный раздел снаружи: у листа с видом открыты «Слои»', () => {
    mount({ sideTab: 'scale', zones: ZONES });
    expect(screen.getByRole('tab', { name: 'Слои' })).toHaveAttribute('aria-selected', 'true');
  });

  it('раздела нет у листа без вида: открыт «Лист», а не первая вкладка', () => {
    mount({ view: null, zones: ZONES, sideTab: 'mep' });
    expect(tabNames()).toEqual(['Зоны', 'Лист']);
    expect(screen.getByRole('tab', { name: 'Лист' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('ход задания j1')).toBeVisible();
  });

  it('«Лист»: блок «Ход преобразования» показывает ход выбранного задания для листа', () => {
    mount();
    openSheet();
    fireEvent.click(screen.getByText('Ход преобразования'));
    expect(fold('Ход преобразования')).toHaveTextContent('ход задания j1');
    expect(mocks.detail.mock.calls.at(-1)?.[0]).toMatchObject({ jobId: 'j1', selectedPage: 0 });
  });

  it('выбранный раздел остаётся при смене диагностики (переходе на другой лист)', () => {
    const view = mount();
    fireEvent.click(screen.getByRole('tab', { name: 'Замечания' }));
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
    expect(screen.getByRole('tab', { name: 'Замечания' })).toHaveAttribute('aria-selected', 'true');
  });

  it('задание есть, вида нет (идёт или отказ): только «Лист», ход открыт', () => {
    mount({ view: null });
    expect(tabNames()).toEqual(['Лист']);
    expect(screen.getByText('ход задания j1')).toBeVisible();
    expect(screen.getByText('ход задания j1').closest('details')).toBeNull();
  });

  it('задание есть, вида нет: профиль и задания документа свёрнуты под ходом', () => {
    mount({
      view: null,
      style: {} as NonNullable<IWorkspaceCadSideProps['style']>,
      jobs: JOBS(),
    });
    expect(fold('Профиль оформления')).not.toHaveAttribute('open');
    expect(fold('Задания документа')).not.toHaveAttribute('open');
  });

  it('вид читается: скелетон в разделе «Лист»', () => {
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

  it('с разделом зон: «Зоны» после «Слоёв», «Лист» последний', () => {
    mount({ zones: ZONES });
    expect(tabNames()).toEqual(['Слои', 'Зоны', 'Замечания', 'Лист']);
    fireEvent.click(screen.getByRole('tab', { name: 'Зоны' }));
    expect(screen.getByText('панель зон')).toBeVisible();
  });

  it('лист без задания: зоны первые, но открыт «Лист» с подсказкой о преобразовании', () => {
    mount({ state: 'none', job: null, view: null, zones: ZONES });
    expect(tabNames()).toEqual(['Зоны', 'Лист']);
    expect(screen.getByRole('tab', { name: 'Лист' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Лист не преобразовывался')).toBeVisible();
    fireEvent.click(screen.getByRole('tab', { name: 'Зоны' }));
    expect(screen.getByText('панель зон')).toBeVisible();
  });

  it('раздел «Конструкции» стоит после «Слоёв», его слой - в панели слоёв', () => {
    mount({ constructions: CONSTRUCTIONS });
    expect(tabNames()).toEqual(['Слои', 'Конструкции', 'Замечания', 'Лист']);
    fireEvent.click(screen.getByRole('tab', { name: 'Конструкции' }));
    expect(screen.getByRole('button', { name: 'Посчитать конструкции' })).toBeVisible();
  });

  it('«Задания документа» - блок «Листа»; список с выбранным заданием, выбор уходит наружу', () => {
    const onSelectJob = vi.fn();
    mount({ jobs: JOBS(onSelectJob) });
    expect(tabNames().at(-1)).toBe('Лист');
    openSheet();
    fireEvent.click(screen.getByText('Задания документа'));
    fireEvent.click(screen.getByText('список заданий, выбрано j7'));
    expect(onSelectJob).toHaveBeenCalledWith('j9');
  });

  it('лист без задания: «Задания документа» и профиль - под подсказкой в «Листе»', () => {
    mount({
      state: 'none',
      job: null,
      view: null,
      style: {} as NonNullable<IWorkspaceCadSideProps['style']>,
      jobs: JOBS(vi.fn(), null),
    });
    expect(tabNames()).toEqual(['Лист']);
    expect(screen.getByText('Лист не преобразовывался')).toBeVisible();
    expect(fold('Профиль оформления')).toHaveTextContent('панель профиля');
    expect(fold('Задания документа')).toHaveTextContent('список заданий, выбрано ничего');
  });

  it('без jobs и style блоков «Задания документа» и «Профиль оформления» нет', () => {
    mount();
    expect(screen.queryByText('Задания документа')).toBeNull();
    expect(screen.queryByText('Профиль оформления')).toBeNull();
  });
});
