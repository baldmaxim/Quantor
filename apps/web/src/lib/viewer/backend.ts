/**
 * Контракт отрисовщика документа.
 *
 * Между рабочей областью и pdf.js стоит интерфейс, а не прямые вызовы (ADR-0004).
 * Смысл в том, что Stage 2/3 сможет добавить тайловый бэкенд для патологически тяжёлых
 * листов, не переписывая ни раскладку, ни слой областей: они работают с этим контрактом.
 *
 * Реализация на pdf.js лежит рядом и загружается только на маршруте рабочей области.
 */

export interface PageGeometry {
  /** Размер страницы в единицах документа при масштабе 1. */
  readonly width: number;
  readonly height: number;
  /** Поворот, заданный в самом документе. */
  readonly rotation: 0 | 90 | 180 | 270;
}

export interface RenderRequest {
  /** Номер страницы с нуля. */
  readonly pageIndex: number;
  readonly scale: number;
  readonly canvas: HTMLCanvasElement;
  /** Отмена устаревшей отрисовки при смене страницы или масштаба. */
  readonly signal: AbortSignal;
}

export interface RenderBackend {
  readonly name: string;
  readonly pageCount: number;

  geometry(pageIndex: number): Promise<PageGeometry>;

  /**
   * Рисует страницу в переданный холст.
   *
   * Обязана прерываться по сигналу: при быстром перелистывании устаревшие задачи должны
   * умирать, а не рисовать поверх актуальной страницы.
   */
  render(request: RenderRequest): Promise<void>;

  destroy(): void;
}

export class RenderCancelledError extends Error {
  constructor() {
    super('Отрисовка отменена');
    this.name = 'RenderCancelledError';
  }
}

export class DocumentLoadError extends Error {
  constructor(
    /** Стабильный код для интерфейса. */
    readonly code: 'PDF_LOAD_FAILED' | 'PDF_RENDER_FAILED' | 'PDF_URL_EXPIRED',
    message: string,
  ) {
    super(message);
    this.name = 'DocumentLoadError';
  }
}
