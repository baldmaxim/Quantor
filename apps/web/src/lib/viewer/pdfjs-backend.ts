'use client';

import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';

import {
  DocumentLoadError,
  RenderCancelledError,
  type PageGeometry,
  type RenderBackend,
  type RenderRequest,
} from './backend';
import { normalizeRotation } from './coordinates';

/**
 * Отрисовщик на pdf.js.
 *
 * Модуль загружается динамически и только на маршруте рабочей области: pdf.js вместе
 * с рабочим потоком весит заметно, и тащить его на список проектов незачем.
 *
 * Документ открывается по временной ссылке прямо из хранилища. Через процесс приложения
 * пятидесятимегабайтный файл не проходит — pdf.js сам запрашивает нужные куски
 * Range-запросами, поэтому первая страница появляется, не дожидаясь остальных 76.
 */

const PAGE_CACHE_LIMIT = 12;

export class PdfJsRenderBackend implements RenderBackend {
  readonly name = 'pdf.js';

  /** Открытые страницы. Их держим ограниченным числом: каждая занимает память. */
  private readonly pages = new Map<number, PDFPageProxy>();
  private destroyed = false;

  private constructor(
    private readonly document: PDFDocumentProxy,
    /** Задача загрузки: только у неё есть destroy, освобождающий рабочий поток. */
    private readonly task: PDFDocumentLoadingTask,
  ) {}

  static async open(url: string, signal?: AbortSignal): Promise<PdfJsRenderBackend> {
    const pdfjs = await import('pdfjs-dist');

    // Рабочий поток обязателен: без него разбор страницы блокирует интерфейс,
    // и панорамирование по большому чертежу превращается в рывки.
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      'pdfjs-dist/build/pdf.worker.min.mjs',
      import.meta.url,
    ).toString();

    const task = pdfjs.getDocument({ url, withCredentials: false });
    signal?.addEventListener('abort', () => void task.destroy(), { once: true });

    try {
      return new PdfJsRenderBackend(await task.promise, task);
    } catch (error) {
      throw toLoadError(error);
    }
  }

  get pageCount(): number {
    return this.document.numPages;
  }

  async geometry(pageIndex: number): Promise<PageGeometry> {
    const page = await this.page(pageIndex);
    const viewport = page.getViewport({ scale: 1 });

    return {
      width: viewport.width,
      height: viewport.height,
      rotation: normalizeRotation(page.rotate),
    };
  }

  async render({ pageIndex, scale, canvas, signal }: RenderRequest): Promise<void> {
    if (signal.aborted) throw new RenderCancelledError();

    const page = await this.page(pageIndex);
    if (signal.aborted) throw new RenderCancelledError();

    // Рисуем в физических пикселях экрана: иначе на мониторе с удвоенной плотностью
    // тонкие линии чертежа расплываются.
    const ratio = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1;
    const viewport = page.getViewport({ scale: scale * ratio });

    canvas.width = Math.max(1, Math.floor(viewport.width));
    canvas.height = Math.max(1, Math.floor(viewport.height));
    canvas.style.width = `${Math.floor(viewport.width / ratio)}px`;
    canvas.style.height = `${Math.floor(viewport.height / ratio)}px`;

    // pdf.js 6: только `canvas`. Вместе с `canvasContext` контекст не берёт
    // переданный холст, а в паре с гонкой это ещё и валит отрисовку.
    const task = page.render({ canvas, viewport });
    const onAbort = () => task.cancel();
    signal.addEventListener('abort', onAbort, { once: true });

    try {
      await task.promise;
    } catch (error) {
      if (signal.aborted || isCancelled(error) || isCanvasBusy(error)) {
        throw new RenderCancelledError();
      }
      throw new DocumentLoadError('PDF_RENDER_FAILED', 'Страница не отрисовалась');
    } finally {
      signal.removeEventListener('abort', onAbort);
    }
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;

    for (const page of this.pages.values()) page.cleanup();
    this.pages.clear();
    void this.task.destroy();
  }

  /** Отдаёт страницу, удерживая в памяти ограниченное их число. */
  private async page(pageIndex: number): Promise<PDFPageProxy> {
    const cached = this.pages.get(pageIndex);
    if (cached) return cached;

    let page: PDFPageProxy;
    try {
      page = await this.document.getPage(pageIndex + 1);
    } catch (error) {
      throw toLoadError(error);
    }

    this.pages.set(pageIndex, page);
    this.evictBeyondLimit(pageIndex);
    return page;
  }

  /**
   * Выселяет страницы, самые далёкие от текущей.
   *
   * Держать все 77 страниц открытыми нельзя — это десятки мегабайт на документ.
   * Выселяем по расстоянию, а не по времени: пользователь листает вперёд-назад,
   * и соседние страницы понадобятся снова.
   */
  private evictBeyondLimit(current: number): void {
    if (this.pages.size <= PAGE_CACHE_LIMIT) return;

    const byDistance = [...this.pages.keys()].sort(
      (a, b) => Math.abs(b - current) - Math.abs(a - current),
    );

    for (const index of byDistance) {
      if (this.pages.size <= PAGE_CACHE_LIMIT) break;
      if (index === current) continue;

      this.pages.get(index)?.cleanup();
      this.pages.delete(index);
    }
  }
}

const isCancelled = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  (error as { name?: string }).name === 'RenderingCancelledException';

const isCanvasBusy = (error: unknown): boolean =>
  error instanceof Error && error.message.includes('same canvas during multiple render');

/**
 * Приводит отказ pdf.js к коду интерфейса.
 *
 * Отдельно распознаём протухшую ссылку: она чинится обновлением, а не сообщением
 * «файл сломан», и путать эти случаи нельзя.
 */
const toLoadError = (error: unknown): DocumentLoadError => {
  const status = (error as { status?: number } | null)?.status;
  if (status === 403 || status === 401) {
    return new DocumentLoadError('PDF_URL_EXPIRED', 'Ссылка на файл истекла');
  }
  return new DocumentLoadError('PDF_LOAD_FAILED', 'Не удалось открыть документ');
};
