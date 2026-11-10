import { fireEvent, render, screen } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as Queries from '@/lib/cad/view-queries';

import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import { diagnostics, FRAME_NO, JOB_ID, preview } from './fixtures';

const state = vi.hoisted(() => ({
  preview: {} as Record<string, unknown>,
  pdf: {} as Record<string, unknown>,
  lastViewport: null as null | Record<string, unknown>,
}));

vi.mock('@/lib/cad/view-queries', async (importOriginal) => ({
  ...(await importOriginal<typeof Queries>()),
  useCadPreview: () => state.preview,
}));
vi.mock('./useCadPdfPage', () => ({ useCadPdfPage: () => state.pdf }));
// Замечания проверяются отдельно (CadViewerPane.remarks.test.tsx); здесь список всегда пуст.
vi.mock('./useCadRemarks', () => ({
  useCadRemarks: () => ({
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
  }),
}));
vi.mock('@/components/viewer/DrawingViewport', () => ({
  DrawingViewport: (props: Record<string, unknown>) => {
    state.lastViewport = props;
    return <div data-testid="viewport" data-has-backend={String(props.backend !== null)} />;
  },
}));

import { CadViewerPane } from './CadViewerPane';

const PARAMS = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: JOB_ID,
  attempt: 1,
  pageIndex: 0,
  view: 1,
};

const EXTRA_TABS = [
  { id: 'scale', label: 'Масштаб', content: <p>содержимое масштаба</p> },
  { id: 'job', label: 'Задание', content: <p>содержимое задания</p> },
];

const mount = (props: Partial<ComponentProps<typeof CadViewerPane>> = {}) =>
  render(
    <CadViewerPane
      params={PARAMS}
      diagnostics={diagnostics()}
      heading={<h3>Стр. 1 · вид 1</h3>}
      extraTabs={EXTRA_TABS}
      {...props}
    />,
  );

const loaded = (data: ReturnType<typeof preview> | undefined) => {
  state.preview = {
    data,
    isPending: data === undefined,
    isError: false,
    refetch: vi.fn(),
  };
};

const pressed = (name: string) =>
  screen.getByRole('button', { name }).getAttribute('aria-pressed') === 'true';

/** Контекст-пустышка с записью вызовов moveTo/lineTo. */
const recordingContext = () => {
  const points: [string, number, number][] = [];
  const context = new Proxy(
    { canvas: { width: 1000, height: 800 } },
    {
      get: (target, key) => {
        if (key in target) return Reflect.get(target, key);
        if (key === 'moveTo' || key === 'lineTo') {
          return (x: number, y: number) => void points.push([String(key), x, y]);
        }
        return () => undefined;
      },
      set: () => true,
    },
  ) as unknown as CanvasRenderingContext2D;
  return { context, points };
};

const PLACEMENT = { x: 0, y: 0, width: 1000, height: 800, rotation: 0 as const };

beforeEach(() => {
  state.pdf = {
    backend: {},
    sheet: { pageIndex: 0, width: 1000, height: 800 },
    loading: false,
    errorCode: null,
    outOfRange: false,
  };
  state.lastViewport = null;
  loaded(preview());
});

describe('CadViewerPane', () => {
  it('кадр подтверждён: по умолчанию наложение, есть слои и непрозрачность', () => {
    mount();
    expect(pressed('Наложение')).toBe(true);
    expect(screen.getByRole('checkbox', { name: 'WALLS' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'DOORS' })).toBeChecked();
    expect(screen.getByRole('slider')).toBeInTheDocument();
    expect(state.lastViewport?.extraPainter).toBeTruthy();
  });

  it('наложение кладёт DXF на страницу по кадру: начало DXF - в origin_pt, ось Y перевёрнута', () => {
    loaded(
      preview({
        paths: [{ layer: 0, closed: false, fill: false, points: [0, 0, 1000, 0, 1000, 1000] }],
      }),
    );
    mount();
    const painter = state.lastViewport?.extraPainter as LayerPainter;
    const { context, points } = recordingContext();
    painter.paint(context, PLACEMENT, 1, null);

    // Первый путь: (0,0) -> origin (37.5; 700); (1000,0) -> x + 1000/35.28; (1000,1000) -> y - 1000/35.28.
    const k = 35.28;
    expect(points[0]).toEqual(['moveTo', 37.5, 700]);
    expect(points[1]?.[1]).toBeCloseTo(37.5 + 1000 / k, 6);
    expect(points[1]?.[2]).toBeCloseTo(700, 6);
    expect(points[2]?.[2]).toBeCloseTo(700 - 1000 / k, 6);
  });

  it('снятый слой пропадает из рисования', () => {
    mount();
    fireEvent.click(screen.getByRole('checkbox', { name: 'DOORS' }));
    expect(screen.getByRole('checkbox', { name: 'DOORS' })).not.toBeChecked();

    const painter = state.lastViewport?.extraPainter as LayerPainter;
    const { context, points } = recordingContext();
    painter.paint(context, PLACEMENT, 1, null);
    // Остался путь слоя WALLS (3 точки, один moveTo); заливка слоя DOORS не рисуется.
    expect(points.filter(([name]) => name === 'moveTo')).toHaveLength(1);
    expect(points).toHaveLength(3);
  });

  it('кадр не подтверждён: наложение недоступно, CAD отдельно и с пояснением', () => {
    loaded(preview({ frame: FRAME_NO }));
    mount({ diagnostics: diagnostics({ frame: FRAME_NO }) });

    expect(screen.getByRole('button', { name: 'Наложение' })).toBeDisabled();
    expect(pressed('CAD')).toBe(true);
    expect(
      screen.getByText(/Сравнение с PDF недоступно: кадр координат не подтверждён/),
    ).toBeInTheDocument();
    expect(state.lastViewport?.backend).toBeNull();
  });

  it('без предпросмотра: только PDF, CAD и наложение недоступны', () => {
    loaded(undefined);
    mount({
      diagnostics: diagnostics({ preview_available: false, dxf: null, frame: FRAME_NO }),
    });

    expect(pressed('PDF')).toBe(true);
    expect(screen.getByRole('button', { name: 'CAD' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Наложение' })).toBeDisabled();
    expect(screen.getByText(/Предпросмотра DXF нет/)).toBeInTheDocument();
    expect(screen.queryByRole('slider')).toBeNull();
  });

  it('упрощённая геометрия: предупреждение с flatten_mm и число точек', () => {
    loaded(preview({ truncated: true, flatten_mm: 2.5, point_count: 12345 }));
    mount();
    expect(
      screen.getByText(/Показана упрощённая геометрия \(flatten_mm 2,5\)/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Точек в предпросмотре/)).toHaveTextContent('12');
  });

  it('предпросмотр другого DXF отвергается', () => {
    loaded(preview({ dxf_sha256: 'c'.repeat(64) }));
    mount();
    expect(screen.getByText('Предпросмотр не относится к DXF этой попытки')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'WALLS' })).toBeNull();
  });

  it('PDF не открылся: ошибка вместо холста', () => {
    state.pdf = { ...state.pdf, backend: null, sheet: null, errorCode: 'PDF_LOAD_FAILED' };
    mount();
    expect(screen.getByText('PDF страницы не показан')).toBeInTheDocument();
  });

  it('контекст масштаба показывается по выбору', () => {
    mount();
    const checkbox = screen.getByRole('checkbox', { name: 'Область проверки масштаба на PDF' });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();

    const painter = state.lastViewport?.extraPainter as LayerPainter;
    const calls: string[] = [];
    const context = new Proxy(
      { canvas: { width: 1000, height: 800 } },
      {
        get: (target, key) =>
          key in target ? Reflect.get(target, key) : () => void calls.push(String(key)),
        set: () => true,
      },
    ) as unknown as CanvasRenderingContext2D;
    painter.paint(context, PLACEMENT, 1, null);
    expect(calls).toContain('strokeRect');
  });

  it('слои рисуются цветами палитры темы: на холсте тот же цвет, что в образце списка', () => {
    const root = document.documentElement;
    root.style.setProperty('--cad-layer-1', 'rgb(1, 2, 3)');
    root.style.setProperty('--cad-layer-2', 'rgb(4, 5, 6)');
    try {
      mount();
      const painter = state.lastViewport?.extraPainter as LayerPainter;
      const strokes: string[] = [];
      let current = '';
      const context = new Proxy(
        { canvas: { width: 1000, height: 800 } },
        {
          get: (target, key) => {
            if (key in target) return Reflect.get(target, key);
            if (key === 'stroke') return () => void strokes.push(current);
            return () => undefined;
          },
          set: (_target, key, value) => {
            if (key === 'strokeStyle') current = String(value);
            return true;
          },
        },
      ) as unknown as CanvasRenderingContext2D;
      painter.paint(context, PLACEMENT, 1, null);
      expect(strokes).toEqual(['rgb(1, 2, 3)', 'rgb(4, 5, 6)']);

      const swatches = screen.getAllByTestId('layer-swatch');
      expect(swatches[0]?.getAttribute('style')).toContain('--cad-layer-1');
      expect(swatches[1]?.getAttribute('style')).toContain('--cad-layer-2');
    } finally {
      root.style.removeProperty('--cad-layer-1');
      root.style.removeProperty('--cad-layer-2');
    }
  });

  it('раскладка: заголовок и режимы над холстом, остальное - в боковой панели с разделами', () => {
    mount();
    expect(screen.getByRole('heading', { name: 'Стр. 1 · вид 1' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Что показывать' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Вписать' })).toBeInTheDocument();

    const panel = screen.getByRole('complementary', { name: 'Панель вида' });
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Слои',
      'Замечания',
      'Масштаб',
      'Задание',
    ]);
    // Слои и непрозрачность - в панели, не над холстом.
    expect(panel).toContainElement(screen.getByRole('slider'));
    expect(panel).toContainElement(screen.getByRole('checkbox', { name: 'WALLS' }));
    expect(panel).not.toContainElement(screen.getByRole('button', { name: 'Вписать' }));

    fireEvent.click(screen.getByRole('tab', { name: 'Задание' }));
    expect(screen.getByText('содержимое задания')).toBeVisible();
    expect(screen.queryByRole('slider')).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: 'Замечания' }));
    expect(screen.getByRole('button', { name: 'Отметить участок' })).toBeInTheDocument();
  });
});
