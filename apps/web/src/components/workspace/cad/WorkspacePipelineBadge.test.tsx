import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/queries', () => ({ useFeatures: () => ({ 'takeoff.manual': true }) }));
vi.mock('@/lib/cad/sheet-queries', () => ({
  useSheetCalibrationStates: (sheets: readonly { page_index: number }[]) =>
    new Map(sheets.map((sheet) => [sheet.page_index, 'calibrated'])),
}));
vi.mock('@/lib/cad/queries', () => ({
  useCreateCadJob: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { useWorkspaceStore } from '@/store/workspace';

import { pipelineOfSheet, pipelineSheet, pipelineView, stage } from './pipeline-fixtures';
import type { IWorkspaceCadConvert } from './types';
import { WorkspacePipelineBadge, type IWorkspacePipelineBadgeProps } from './WorkspacePipelineBadge';

const CONVERT: IWorkspaceCadConvert = {
  projectId: 'p1',
  revisionId: 'r1',
  sheetId: 's2',
  pageIndex: 2,
  onCalibrate: vi.fn(),
  onJobCreated: vi.fn(),
};

/** Лист на шаге «Принять трассы»: преобразование готово, поэтому есть «Преобразовать заново». */
const routesReviewSheet = () =>
  pipelineSheet({
    views: [pipelineView({ approved: true, routes: stage({ job_id: 'rt1', job_type: 'cad_mep_route' }) })],
  });

const mount = (patch: Partial<IWorkspacePipelineBadgeProps> = {}) => {
  const props: IWorkspacePipelineBadgeProps = {
    pipeline: pipelineOfSheet(pipelineSheet()),
    cadOn: true,
    convert: CONVERT,
    openablePanels: ['mep', 'constructions'],
    onOpenPanel: vi.fn(),
    ...patch,
  };
  return { ...render(<WorkspacePipelineBadge {...props} />), props };
};

const badge = () => screen.getByRole('button', { name: /^Обработка листа:/ });
const popover = () => screen.queryByRole('dialog', { name: 'Обработка листа' });
const open = () => fireEvent.click(badge());

describe('WorkspacePipelineBadge', () => {
  beforeEach(() => useWorkspaceStore.setState({ mode: 'sheets', tool: 'pointer' }));

  it('итог листа: подпись и aria-label', () => {
    mount();
    expect(badge()).toHaveAccessibleName('Обработка листа: Нужно: одобрить вид');
    expect(badge()).toHaveTextContent('Нужно: одобрить вид');
  });

  it('ошибка этапа - в подписи', () => {
    const sheet = pipelineSheet({ convert: stage({ status: 'failed' }), views: [] });
    mount({ pipeline: pipelineOfSheet(sheet) });
    expect(screen.getByRole('button', { name: 'Обработка листа: Ошибка: CAD' })).toBeInTheDocument();
  });

  it('лист не в конвейере: «Лист не обрабатывался»', () => {
    mount({ pipeline: pipelineOfSheet(null) });
    expect(screen.getByRole('button', { name: 'Обработка листа: Лист не обрабатывался' })).toBeInTheDocument();
  });

  it('загрузка: ничего', () => {
    const { container } = mount({ pipeline: pipelineOfSheet(null, { isPending: true }) });
    expect(container).toBeEmptyDOMElement();
  });

  it('ошибка загрузки: ничего', () => {
    const { container } = mount({ pipeline: pipelineOfSheet(null, { isError: true }) });
    expect(container).toBeEmptyDOMElement();
  });

  it('без cad.export: ничего', () => {
    const { container } = mount({ cadOn: false });
    expect(container).toBeEmptyDOMElement();
  });

  describe('окно обработки', () => {
    it('закрыто, пока бейдж не нажат; нажатие открывает окно и переводит фокус в него', () => {
      mount();
      expect(badge()).toHaveAttribute('aria-haspopup', 'dialog');
      expect(badge()).toHaveAttribute('aria-expanded', 'false');
      expect(popover()).toBeNull();
      open();
      expect(badge()).toHaveAttribute('aria-expanded', 'true');
      expect(popover()).toBeInTheDocument();
      expect(popover()).toHaveFocus();
      expect(within(popover() as HTMLElement).getByRole('list', { name: 'Шаги обработки листа' })).toBeInTheDocument();
    });

    it('повторное нажатие на бейдж закрывает окно', () => {
      mount();
      open();
      fireEvent.pointerDown(badge());
      fireEvent.click(badge());
      expect(popover()).toBeNull();
    });

    it('Esc закрывает окно и возвращает фокус на бейдж', () => {
      mount();
      open();
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(popover()).toBeNull();
      expect(badge()).toHaveFocus();
    });

    it('нажатие вне окна закрывает его, внутри - нет', () => {
      mount();
      open();
      fireEvent.pointerDown(within(popover() as HTMLElement).getByText('Обработка листа'));
      expect(popover()).toBeInTheDocument();
      fireEvent.pointerDown(document.body);
      expect(popover()).toBeNull();
    });

    it('крестик закрывает окно', () => {
      mount();
      open();
      fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
      expect(popover()).toBeNull();
      expect(badge()).toHaveFocus();
    });

    it('диалог подтверждения «Преобразовать заново»: Esc и нажатия внутри окно не закрывают', () => {
      mount({ pipeline: pipelineOfSheet(routesReviewSheet()) });
      open();
      fireEvent.click(screen.getByRole('button', { name: 'Преобразовать заново' }));
      const confirm = screen.getByRole('dialog', { name: 'Преобразовать лист заново?' });

      fireEvent.pointerDown(within(confirm).getByText(/Лист будет преобразован/));
      expect(popover()).toBeInTheDocument();
      // Подложка диалога лежит вне него и вне окна обработки: тоже не «вне».
      fireEvent.pointerDown(confirm.parentElement as HTMLElement);
      expect(popover()).toBeInTheDocument();

      fireEvent.keyDown(document, { key: 'Escape' });
      expect(popover()).toBeInTheDocument();
    });

    it('«Проверить трассы» открывает раздел «mep», включает режим CAD и закрывает окно', () => {
      const { props } = mount({ pipeline: pipelineOfSheet(routesReviewSheet()) });
      open();
      fireEvent.click(screen.getByRole('button', { name: 'Проверить трассы' }));
      expect(props.onOpenPanel).toHaveBeenCalledWith('mep');
      expect(useWorkspaceStore.getState().mode).toBe('cad');
      expect(popover()).toBeNull();
    });

    it('включение инструмента «Масштаб» («Откалибровать») закрывает окно', () => {
      mount();
      open();
      act(() => useWorkspaceStore.setState({ tool: 'scale' }));
      expect(popover()).toBeNull();
    });

    it('инструмент «Масштаб» уже включён: окно открывается и остаётся', () => {
      useWorkspaceStore.setState({ tool: 'scale' });
      mount();
      open();
      expect(popover()).toBeInTheDocument();
    });
  });
});
