import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { diagnostics } from '@/components/cad/viewer/fixtures';
import type { ICadRemarks } from '@/components/cad/viewer/useCadRemarks';

import type { IWorkspaceCadPanelProps, IWorkspaceCadRecognized } from './types';
import { WorkspaceCadPanel } from './WorkspaceCadPanel';

const HREF = '/projects/p/cad?revision=r';

const base = (patch: Partial<IWorkspaceCadPanelProps> = {}): IWorkspaceCadPanelProps => ({
  state: 'none',
  sheetLabel: '3',
  cadHref: HREF,
  loadError: null,
  onRetry: vi.fn(),
  recognized: null,
  ...patch,
});

const store = (patch: Partial<ICadRemarks> = {}): ICadRemarks => ({
  remarks: [],
  loading: false,
  loadError: null,
  reload: vi.fn(),
  reviewer: '',
  setReviewer: vi.fn(),
  saving: false,
  error: null,
  add: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  importFile: vi.fn(),
  ...patch,
});

const recognized = (patch: Partial<IWorkspaceCadRecognized> = {}): IWorkspaceCadRecognized => ({
  resultStatus: 'completed_requires_review',
  loading: false,
  error: null,
  diagnostics: diagnostics({ scale: { ...diagnostics().scale!, deviation: 0.023 } }),
  views: [1],
  view: 1,
  onViewChange: vi.fn(),
  overlay: true,
  overlayAvailable: true,
  overlayReason: null,
  overlayLoading: false,
  overlayError: null,
  onOverlayChange: vi.fn(),
  remarks: null,
  ...patch,
});

describe('WorkspaceCadPanel', () => {
  it('лист не преобразовывался - текст и ссылка на страницу CAD', () => {
    render(<WorkspaceCadPanel {...base()} />);
    expect(screen.getByText('Лист не преобразовывался')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть страницу CAD' })).toHaveAttribute(
      'href',
      HREF,
    );
  });

  it('задание выполняется - бейдж и ссылка на задание', () => {
    render(<WorkspaceCadPanel {...base({ state: 'running', cadHref: `${HREF}&job=j` })} />);
    expect(screen.getByText('Выполняется')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть задание на странице CAD' })).toHaveAttribute(
      'href',
      `${HREF}&job=j`,
    );
  });

  it('ошибка - бейдж и ссылка на задание', () => {
    render(<WorkspaceCadPanel {...base({ state: 'failed', cadHref: `${HREF}&job=j` })} />);
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Открыть задание на странице CAD' }),
    ).toBeInTheDocument();
  });

  it('распознан: итог, масштаб с отклонением, приёмка не выполнена, переключатель наложения', () => {
    const model = recognized();
    render(<WorkspaceCadPanel {...base({ state: 'recognized', recognized: model })} />);
    expect(screen.getByText(/DXF выпущен · нужна проверка/)).toBeInTheDocument();
    expect(screen.getByText('Инженерная приёмка: не выполнена')).toBeInTheDocument();
    expect(screen.getByText('2,3 %')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть на странице CAD' })).toHaveAttribute(
      'href',
      HREF,
    );
    // один вид - переключателя видов нет
    expect(screen.queryByRole('group', { name: 'Вид листа' })).toBeNull();

    const toggle = screen.getByRole('checkbox', { name: 'DXF поверх чертежа' });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    expect(model.onOverlayChange).toHaveBeenCalledWith(false);
  });

  it('несколько видов - выбор вида', () => {
    const model = recognized({ views: [1, 2], view: 1 });
    render(<WorkspaceCadPanel {...base({ state: 'recognized', recognized: model })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Вид 2' }));
    expect(model.onViewChange).toHaveBeenCalledWith(2);
  });

  it('наложение недоступно: переключатель выключен, причина видна', () => {
    const model = recognized({
      overlayAvailable: false,
      overlayReason: 'Кадр координат не подтверждён: DXF не накладывается.',
    });
    render(<WorkspaceCadPanel {...base({ state: 'recognized', recognized: model })} />);
    const toggle = screen.getByRole('checkbox', { name: 'DXF поверх чертежа' });
    expect(toggle).toBeDisabled();
    expect(toggle).not.toBeChecked();
    expect(screen.getByText(/Кадр координат не подтверждён/)).toBeInTheDocument();
  });

  it('диагностика ещё читается - скелетон; отказ - ошибка с кодом', () => {
    const { rerender } = render(
      <WorkspaceCadPanel
        {...base({
          state: 'recognized',
          recognized: recognized({ loading: true, diagnostics: null }),
        })}
      />,
    );
    expect(screen.getByRole('status', { name: 'Загрузка вида' })).toBeInTheDocument();

    rerender(
      <WorkspaceCadPanel
        {...base({
          state: 'recognized',
          recognized: recognized({
            diagnostics: null,
            error: { code: 'CAD_RESULT_NOT_READY', text: 'Результат попытки ещё не готов' },
          }),
        })}
      />,
    );
    expect(screen.getByText('Результат CAD не загружен')).toBeInTheDocument();
  });

  it('замечания вида подключены той же панелью, что на странице CAD', () => {
    const remarks = {
      binding: {
        projectId: 'p',
        revisionId: 'r',
        jobId: 'j',
        attempt: 1,
        pageIndex: 0,
        legacyPdfPage: 1,
        view: 1,
        dxfSha256: null,
      },
      store: store(),
      page: { width: 842, height: 595 },
      marking: false,
      onMarkingChange: vi.fn(),
      markDisabledReason: null,
      draft: null,
      onDraftSave: vi.fn(),
      onDraftCancel: vi.fn(),
      activeId: null,
      onActivate: vi.fn(),
      onFocusCamera: vi.fn(),
      viewport: () => ({ width: 800, height: 600 }),
    };
    render(
      <WorkspaceCadPanel {...base({ state: 'recognized', recognized: recognized({ remarks }) })} />,
    );
    expect(screen.getByTestId('cad-remarks')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Отметить участок' }));
    expect(remarks.onMarkingChange).toHaveBeenCalledWith(true);
  });

  it('лист не выбран, загрузка и ошибка списка заданий', () => {
    const { rerender } = render(<WorkspaceCadPanel {...base({ state: 'no-sheet' })} />);
    expect(screen.getByText('Лист не выбран.')).toBeInTheDocument();

    rerender(<WorkspaceCadPanel {...base({ state: 'loading' })} />);
    expect(screen.getByRole('status', { name: 'Загрузка заданий CAD' })).toBeInTheDocument();

    const onRetry = vi.fn();
    rerender(<WorkspaceCadPanel {...base({ state: 'error', loadError: 'Нет связи', onRetry })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalled();
  });
});
