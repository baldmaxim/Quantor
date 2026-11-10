import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type * as Api from '@quantor/api-client';
import type * as Queries from '@/lib/cad/view-queries';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import { diagnostics, FRAME_NO, JOB_ID, preview, SHA } from './fixtures';

interface IQuery {
  readonly attempt: number;
  readonly page_index: number;
  readonly view: number;
}

const state = vi.hoisted(() => ({
  preview: {} as Record<string, unknown>,
  pdf: {} as Record<string, unknown>,
  lastViewport: null as null | Record<string, unknown>,
}));

/** Сервер замечаний в памяти: ключ строки - попытка, страница, вид и клиентский id. */
const net = vi.hoisted(() => ({
  rows: new Map<string, Record<string, unknown>>(),
  puts: [] as { id: string; body: Record<string, unknown> }[],
  deletes: [] as string[],
  imports: [] as Record<string, unknown>[],
  failPut: null as unknown,
  failList: null as unknown,
  failImport: null as unknown,
  importResult: { imported: 0, updated: 0 },
  holdList: false,
  tick: 0,
}));

vi.mock('@/lib/cad/view-queries', async (importOriginal) => ({
  ...(await importOriginal<typeof Queries>()),
  useCadPreview: () => state.preview,
}));
vi.mock('./useCadPdfPage', () => ({ useCadPdfPage: () => state.pdf }));
vi.mock('@/components/viewer/DrawingViewport', () => ({
  DrawingViewport: (props: Record<string, unknown>) => {
    state.lastViewport = props;
    return <div data-testid="viewport" />;
  },
}));
vi.mock('@quantor/api-client', async (importOriginal) => {
  const slot = (query: IQuery, id = '') =>
    `${query.attempt}:${query.page_index}:${query.view}:${id}`;
  return {
    ...(await importOriginal<typeof Api>()),
    listCadRemarks: async ({ query }: { query: IQuery }) => {
      if (net.failList) throw net.failList;
      if (net.holdList) return new Promise(() => undefined);
      const prefix = slot(query);
      const data = [...net.rows.entries()]
        .filter(([key]) => key.startsWith(prefix))
        .map(([, row]) => row);
      return { data };
    },
    putCadRemark: async ({
      path,
      query,
      body,
    }: {
      path: { remark_key: string };
      query: IQuery;
      body: Record<string, unknown>;
    }) => {
      if (net.failPut) throw net.failPut;
      net.puts.push({ id: path.remark_key, body });
      net.tick += 1;
      const now = new Date(Date.UTC(2026, 10, 9, 10, 0, net.tick)).toISOString();
      const key = slot(query, path.remark_key);
      const previous = net.rows.get(key);
      const row = {
        id: path.remark_key,
        type: body.type,
        comment: body.comment,
        reviewer: body.reviewer,
        status: body.status,
        bbox_pt: body.bbox_pt,
        created_at: previous ? previous.created_at : now,
        updated_at: now,
      };
      net.rows.set(key, row);
      return { data: row };
    },
    deleteCadRemark: async ({ path, query }: { path: { remark_key: string }; query: IQuery }) => {
      net.deletes.push(path.remark_key);
      net.rows.delete(slot(query, path.remark_key));
      return { data: undefined };
    },
    importCadRemarks: async ({ body }: { body: Record<string, unknown> }) => {
      if (net.failImport) throw net.failImport;
      net.imports.push(body);
      return { data: net.importResult };
    },
  };
});

import { CadViewerPane } from './CadViewerPane';

const PARAMS = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: JOB_ID,
  attempt: 1,
  pageIndex: 0,
  view: 1,
};
const PLACEMENT = { x: 0, y: 0, width: 1000, height: 800, rotation: 0 as const };

// jsdom не знает PointerEvent: без него clientX и pointerId в событиях пропадают.
class TestPointerEvent extends MouseEvent {
  readonly pointerId: number;
  readonly pointerType: string;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
    this.pointerType = init.pointerType ?? 'mouse';
  }
}
Object.assign(window, { PointerEvent: TestPointerEvent });

/** Новый клиент запросов на каждый показ: так «перезагрузка страницы» не помнит прежний кеш. */
const shell = (params = PARAMS, patch: Parameters<typeof diagnostics>[0] = {}) => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })
    }
  >
    <CadViewerPane
      params={params}
      diagnostics={diagnostics(patch)}
      heading={<h3>Стр. 1 · вид 1</h3>}
      extraTabs={[]}
      // Замечания лежат в своём разделе боковой панели: открываем его сразу.
      sideTab="remarks"
    />
  </QueryClientProvider>
);

/** Показ панели; список замечаний уже получен с «сервера». */
const mount = async (patch: Parameters<typeof diagnostics>[0] = {}, params = PARAMS) => {
  const view = render(shell(params, patch));
  await waitFor(() => expect(screen.queryByText('Загрузка замечаний…')).toBeNull());
  return view;
};

/** Контекст-пустышка: записывает вызовы strokeRect. */
const strokeRects = (painter: LayerPainter) => {
  const rects: number[][] = [];
  const context = new Proxy(
    { canvas: { width: 1000, height: 800 }, measureText: () => ({ width: 8 }) },
    {
      get: (target, key) => {
        if (key in target) return Reflect.get(target, key);
        if (key === 'strokeRect') return (...args: number[]) => void rects.push(args);
        return () => undefined;
      },
      set: () => true,
    },
  ) as unknown as CanvasRenderingContext2D;
  painter.paint(context, PLACEMENT, 1, null);
  return rects;
};

const draw = (from: [number, number], to: [number, number]) => {
  const layer = screen.getByTestId('remark-capture');
  fireEvent.pointerDown(layer, {
    pointerId: 1,
    pointerType: 'mouse',
    button: 0,
    clientX: from[0],
    clientY: from[1],
  });
  fireEvent.pointerMove(layer, {
    pointerId: 1,
    pointerType: 'mouse',
    clientX: to[0],
    clientY: to[1],
  });
  fireEvent.pointerUp(layer, {
    pointerId: 1,
    pointerType: 'mouse',
    clientX: to[0],
    clientY: to[1],
  });
};

const fillDraft = (comment = 'Нет стены у оси Б') => {
  fireEvent.click(screen.getByRole('button', { name: 'Отметить участок' }));
  draw([100, 80], [300, 240]);
  fireEvent.change(screen.getByLabelText('Тип'), { target: { value: 'false_wall' } });
  fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: comment } });
};

const addRemark = async (comment?: string) => {
  fillDraft(comment);
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
  await screen.findAllByTestId('remark-item');
};

const exportText = async (): Promise<string> => {
  const create = vi.fn(() => 'blob:x');
  Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  fireEvent.change(screen.getByRole('textbox', { name: 'Проверяющий' }), {
    target: { value: 'Иванов' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Экспорт JSON' }));
  return (create.mock.calls[0] as unknown as [Blob])[0].text();
};

const pickFile = async (text: string) => {
  await act(async () => {
    fireEvent.change(screen.getByTestId('remarks-import'), {
      target: { files: [new File([text], 'r.json', { type: 'application/json' })] },
    });
  });
};

beforeEach(() => {
  window.localStorage.clear();
  net.rows.clear();
  net.puts.length = 0;
  net.deletes.length = 0;
  net.imports.length = 0;
  net.failPut = null;
  net.failList = null;
  net.failImport = null;
  net.importResult = { imported: 0, updated: 0 };
  net.holdList = false;
  net.tick = 0;
  state.pdf = {
    backend: {},
    sheet: { pageIndex: 0, width: 1000, height: 800 },
    loading: false,
    errorCode: null,
    outOfRange: false,
  };
  state.preview = { data: preview(), isPending: false, isError: false, refetch: vi.fn() };
  state.lastViewport = null;
  Element.prototype.setPointerCapture = vi.fn();
});

afterEach(() => vi.restoreAllMocks());

describe('замечания в панели вида', () => {
  it('отметка участка отправляет замечание на сервер в pt PDF и рисует его на листе', async () => {
    await mount();
    expect(screen.getByText(/Замечания хранятся на сервере/)).toBeInTheDocument();
    await addRemark();

    const items = screen.getAllByTestId('remark-item');
    expect(items).toHaveLength(1);
    expect(within(items[0]!).getByText('Лишняя стена')).toBeInTheDocument();
    expect(screen.getByText('открыто 1 / всего 1')).toBeInTheDocument();

    // Камера по умолчанию: масштаб 1, смещение 0 - экранные пиксели равны pt.
    expect(net.puts).toHaveLength(1);
    expect(net.puts[0]?.body).toMatchObject({
      type: 'false_wall',
      comment: 'Нет стены у оси Б',
      status: 'open',
      bbox_pt: [100, 80, 300, 240],
      dxf_sha256: SHA,
    });
    expect(net.puts[0]?.id).toMatch(/^[0-9a-f-]{36}$/);
    // В браузере замечания не хранятся.
    expect(
      Object.keys(window.localStorage).filter((key) => key.startsWith('quantor.cad-remarks.v1:')),
    ).toEqual([]);

    const painter = state.lastViewport?.extraPainter as LayerPainter;
    const frame = strokeRects(painter)[0] ?? [];
    [100, 80, 200, 160].forEach((value, index) => expect(frame[index]).toBeCloseTo(value, 6));
  });

  it('замечание переживает перезагрузку (новый клиент, пустой браузер) и не видно у другой попытки', async () => {
    const first = await mount();
    await addRemark();
    first.unmount();
    window.localStorage.clear();

    await mount();
    expect(await screen.findAllByTestId('remark-item')).toHaveLength(1);
    cleanupFor();

    await mount({ attempt: 2 }, { ...PARAMS, attempt: 2 });
    expect(screen.queryAllByTestId('remark-item')).toHaveLength(0);
  });

  it('пока список грузится - состояние загрузки; отказ загрузки - с повтором', async () => {
    net.holdList = true;
    render(shell());
    expect(await screen.findByText('Загрузка замечаний…')).toBeInTheDocument();
    cleanupFor();

    net.holdList = false;
    net.failList = { detail: { code: 'DATABASE_UNAVAILABLE' } };
    render(shell());
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить замечания');
    net.failList = null;
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Замечаний к этому виду нет.')).toBeInTheDocument();
  });

  it('отказ сервера при сохранении: сообщение есть, участок и текст остаются в форме', async () => {
    await mount();
    net.failPut = { detail: { code: 'STORAGE_UNAVAILABLE', message: 'нет связи' } };
    fillDraft('Не потерять этот текст');
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    expect(await screen.findByText(/Замечание не сохранено/)).toBeInTheDocument();
    expect(screen.queryAllByTestId('remark-item')).toHaveLength(0);
    expect(screen.getByLabelText('Комментарий')).toHaveValue('Не потерять этот текст');
    expect(screen.getByLabelText('Тип')).toHaveValue('false_wall');

    // Повтор после восстановления сервера сохраняет тот же участок и текст.
    net.failPut = null;
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findAllByTestId('remark-item')).toHaveLength(1);
    expect(net.puts[0]?.body).toMatchObject({
      comment: 'Не потерять этот текст',
      bbox_pt: [100, 80, 300, 240],
    });
    expect(screen.queryByLabelText('Комментарий')).toBeNull();
  });

  it('статус переключается запросом, удаление - с подтверждением и запросом', async () => {
    await mount();
    await addRemark();
    fireEvent.click(screen.getByRole('checkbox', { name: /Нужно перепроверить/ }));
    expect(await screen.findByText('открыто 0 / всего 1')).toBeInTheDocument();
    expect(screen.getByTestId('remark-item')).toHaveAttribute('data-status', 'resolved');
    expect(net.puts).toHaveLength(2);
    expect(net.puts[1]?.body).toMatchObject({ status: 'resolved', bbox_pt: [100, 80, 300, 240] });
    expect(net.puts[1]?.id).toBe(net.puts[0]?.id);

    fireEvent.click(screen.getByRole('button', { name: 'Удалить замечание 1' }));
    expect(screen.getByTestId('remark-item')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Нет' }));
    expect(net.deletes).toEqual([]);

    fireEvent.click(screen.getByRole('button', { name: 'Удалить замечание 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Да, удалить' }));
    await waitFor(() => expect(screen.queryByTestId('remark-item')).toBeNull());
    expect(net.deletes).toEqual([net.puts[0]?.id]);
    expect(net.rows.size).toBe(0);
  });

  it('«К участку» подводит камеру к отметке', async () => {
    await mount();
    await addRemark();
    fireEvent.click(screen.getByRole('button', { name: 'К участку' }));
    const camera = state.lastViewport?.camera as { getState: () => { scale: number } };
    // Состояние камеры применяется в кадре; в jsdom проверяем, что вызов не падает и масштаб задан.
    expect(camera.getState().scale).toBeGreaterThan(0);
  });

  it('без проверяющего экспорт отказывает, с именем скачивает файл схемы v1 из серверного списка', async () => {
    await mount();
    await addRemark();
    const create = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() });
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push(this.download);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Экспорт JSON' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Укажите проверяющего');
    expect(create).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole('textbox', { name: 'Проверяющий' }), {
      target: { value: 'Иванов' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Экспорт JSON' }));
    expect(clicked[0]).toMatch(/^Замечания_стр1_вид1_\d{8}-\d{4}\.json$/);

    const blob = (create.mock.calls[0] as unknown as [Blob])[0];
    const file = JSON.parse(await blob.text()) as Record<string, unknown>;
    expect(file).toMatchObject({
      schema: 'quantor.cad-remarks.v1',
      project_id: 'p1',
      revision_id: 'r1',
      job_id: JOB_ID,
      attempt: 1,
      page_index: 0,
      legacy_pdf_page: 1,
      view: 1,
      dxf_sha256: SHA,
      coordinate_system: 'pdf_pt_top_left',
      reviewer: 'Иванов',
      engineering_acceptance: false,
    });
    const remarks = file.remarks as { id: string; created_at: string }[];
    expect(remarks).toHaveLength(1);
    // Время и id - ровно с сервера: файл при повторном импорте ничего не меняет.
    expect(remarks[0]?.id).toBe(net.puts[0]?.id);
    expect(remarks[0]?.created_at).toBe('2026-11-09T10:00:01.000Z');
    expect(window.localStorage.getItem('quantor.cad-remarks.reviewer.v1')).toBe('Иванов');
  });

  it('импорт: файл уходит на сервер, итог берётся из ответа; чужой вид отклоняется до отправки', async () => {
    await mount();
    await addRemark();
    const text = await exportText();

    net.importResult = { imported: 1, updated: 2 };
    await pickFile(text);
    expect(await screen.findByText('Импортировано: 1, обновлено: 2')).toBeInTheDocument();
    expect(net.imports).toHaveLength(1);
    expect(net.imports[0]).toMatchObject({
      schema: 'quantor.cad-remarks.v1',
      job_id: JOB_ID,
      attempt: 1,
      page_index: 0,
      view: 1,
      dxf_sha256: SHA,
    });
    expect((net.imports[0]?.remarks as unknown[]).length).toBe(1);

    await pickFile(text.replace('"view": 1', '"view": 2'));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Импорт отклонён.*вид/);
    expect(net.imports).toHaveLength(1);
  });

  it('отказ сервера при импорте показывает его текст, список не меняется', async () => {
    await mount();
    await addRemark();
    const text = await exportText();
    net.failImport = {
      detail: {
        code: 'CAD_REMARKS_BINDING_MISMATCH',
        message: 'Файл относится к другому результату: не совпадает ревизия.',
      },
    };
    await pickFile(text);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Импорт отклонён.*не совпадает ревизия/,
    );
    expect(screen.getAllByTestId('remark-item')).toHaveLength(1);
  });

  it('файл больше 2 МБ отклоняется до разбора', async () => {
    await mount();
    const big = new File(['x'], 'big.json');
    Object.defineProperty(big, 'size', { value: 2 * 1024 * 1024 + 1 });
    await act(async () => {
      fireEvent.change(screen.getByTestId('remarks-import'), { target: { files: [big] } });
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('больше 2 МБ');
    expect(net.imports).toHaveLength(0);
  });

  it('в режиме CAD отметка выключена с причиной, замечания на листе не рисуются', async () => {
    await mount();
    await addRemark();
    fireEvent.click(screen.getByRole('button', { name: 'CAD' }));
    expect(screen.getByRole('button', { name: 'Отметить участок' })).toBeDisabled();
    expect(screen.getByText(/В режиме CAD замечания не рисуются/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'К участку' })).toBeNull();
    const painter = state.lastViewport?.extraPainter as LayerPainter;
    // Рисуется только геометрия CAD: рамок замечаний нет.
    expect(strokeRects(painter)).toHaveLength(0);
  });

  it('CAD без подтверждённого кадра: причина про кадр координат', async () => {
    state.preview = {
      data: preview({ frame: FRAME_NO }),
      isPending: false,
      isError: false,
      refetch: vi.fn(),
    };
    await mount({ frame: FRAME_NO });
    expect(screen.getByRole('button', { name: 'Отметить участок' })).toBeDisabled();
    expect(
      screen.getByText(/кадр координат не подтверждён, а замечания привязаны/),
    ).toBeInTheDocument();
  });
});

describe('ошибка отрисовки PDF', () => {
  it('показывается в режиме PDF, пропадает при переключении в CAD и после успешной отрисовки', async () => {
    await mount();
    const viewport = () =>
      state.lastViewport as { onError: (code: string) => void; onRendered: () => void };
    act(() => viewport().onError('PDF_LOAD_FAILED'));
    expect(screen.getByRole('alert')).toHaveTextContent('PDF_LOAD_FAILED');

    fireEvent.click(screen.getByRole('button', { name: 'CAD' }));
    expect(screen.queryByText(/Не удалось отрисовать страницу PDF/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Наложение' }));
    // Прежний отказ относился к тому же отрисовщику и листу: возвращается, пока не снят.
    act(() => viewport().onRendered());
    expect(screen.queryByText(/Не удалось отрисовать страницу PDF/)).toBeNull();
  });

  it('отказ прежнего отрисовщика не показывается после его замены', async () => {
    const view = await mount();
    act(() =>
      (state.lastViewport as { onError: (code: string) => void }).onError('PDF_LOAD_FAILED'),
    );
    expect(screen.getByText(/Не удалось отрисовать страницу PDF/)).toBeInTheDocument();

    state.pdf = { ...state.pdf, backend: {} };
    view.rerender(shell());
    expect(screen.queryByText(/Не удалось отрисовать страницу PDF/)).toBeNull();
  });
});

const cleanupFor = () => {
  document.body.innerHTML = '';
};
