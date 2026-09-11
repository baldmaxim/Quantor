/**
 * Пространственный индекс охватов в нормализованных координатах листа (промт 04).
 *
 * Равномерная сетка поверх единичного квадрата листа. Запись лежит во всех ячейках, которые задевает
 * её охват; поиск обходит ячейки прямоугольника и снимает повторы меткой поиска. Выбрана микрозамером
 * против линейного перебора, R-дерева `rbush` и упакованного `flatbush` (`docs/stage2b/04-spatial-index.md`):
 * попадание на 25 000 объектов — сотые доли миллисекунды, обновление одной записи — без перестройки,
 * а статичный `flatbush` на каждую правку перестраивается целиком.
 *
 * Индекс ничего не знает о фигурах: ключ и охват. Им пользуются слой измерений и будет пользоваться
 * слой AI-кандидатов.
 */

/** Охват в нормализованных координатах листа: [0, 1] от левого верхнего угла. */
export interface NormalizedBounds {
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
}

export interface SpatialIndex<K> {
  /** Число записей. */
  readonly size: number;
  /** Ставит запись или переносит существующую — без перестройки индекса. */
  set(key: K, bounds: NormalizedBounds): void;
  /** Убирает запись. `false` — такой не было. */
  delete(key: K): boolean;
  /** Ключи записей, чей охват пересекает прямоугольник (с касанием). Порядок не гарантирован. */
  search(bounds: NormalizedBounds): K[];
  clear(): void;
}

interface Entry<K> {
  readonly key: K;
  bounds: NormalizedBounds;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  /** Номер последнего поиска, видевшего запись: запись в нескольких ячейках отдаётся один раз. */
  mark: number;
}

/**
 * Ячеек по стороне по умолчанию. Замер: 32 и 64 дают одно и то же попадание, 32 строится втрое
 * быстрее на крупных охватах, 128 проигрывает на диапазонах и памяти.
 */
export const DEFAULT_CELLS_PER_SIDE = 32;

const intersects = (a: NormalizedBounds, b: NormalizedBounds): boolean =>
  a.maxX >= b.minX && a.minX <= b.maxX && a.maxY >= b.minY && a.minY <= b.maxY;

const finite = (bounds: NormalizedBounds): boolean =>
  Number.isFinite(bounds.minX) &&
  Number.isFinite(bounds.minY) &&
  Number.isFinite(bounds.maxX) &&
  Number.isFinite(bounds.maxY) &&
  bounds.minX <= bounds.maxX &&
  bounds.minY <= bounds.maxY;

export class GridIndex<K> implements SpatialIndex<K> {
  private readonly cells: Entry<K>[][];
  private readonly entries = new Map<K, Entry<K>>();
  // Записи с неконечным или вывернутым охватом. Их нет ни в одной ячейке, и поиск их не отдаёт:
  // фигуру без геометрии не видно и в неё не попасть. Храним, чтобы `delete` и `size` были честны.
  private readonly degenerate = new Set<K>();
  private stamp = 0;

  constructor(private readonly cellsPerSide = DEFAULT_CELLS_PER_SIDE) {
    this.cells = Array.from({ length: cellsPerSide * cellsPerSide }, () => []);
  }

  get size(): number {
    return this.entries.size + this.degenerate.size;
  }

  set(key: K, bounds: NormalizedBounds): void {
    if (!finite(bounds)) {
      this.delete(key);
      this.degenerate.add(key);
      return;
    }
    this.degenerate.delete(key);

    const [x0, y0, x1, y1] = this.cellRange(bounds);
    const existing = this.entries.get(key);
    if (
      existing &&
      existing.x0 === x0 &&
      existing.y0 === y0 &&
      existing.x1 === x1 &&
      existing.y1 === y1
    ) {
      // Те же ячейки — достаточно заменить охват.
      existing.bounds = bounds;
      return;
    }
    if (existing) this.unlink(existing);

    const entry: Entry<K> = { key, bounds, x0, y0, x1, y1, mark: 0 };
    this.entries.set(key, entry);
    this.link(entry);
  }

  delete(key: K): boolean {
    if (this.degenerate.delete(key)) return true;
    const entry = this.entries.get(key);
    if (!entry) return false;
    this.unlink(entry);
    this.entries.delete(key);
    return true;
  }

  search(bounds: NormalizedBounds): K[] {
    const found: K[] = [];
    if (!finite(bounds)) return found;

    this.stamp += 1;
    const stamp = this.stamp;
    const [x0, y0, x1, y1] = this.cellRange(bounds);
    for (let y = y0; y <= y1; y += 1) {
      for (let x = x0; x <= x1; x += 1) {
        const cell = this.cells[y * this.cellsPerSide + x] ?? [];
        for (const entry of cell) {
          if (entry.mark === stamp) continue;
          entry.mark = stamp;
          if (intersects(entry.bounds, bounds)) found.push(entry.key);
        }
      }
    }
    return found;
  }

  clear(): void {
    for (const cell of this.cells) cell.length = 0;
    this.entries.clear();
    this.degenerate.clear();
  }

  /** Сколько ссылок лежит в ячейках — для оценки памяти в замере. */
  cellReferences(): number {
    return this.cells.reduce((total, cell) => total + cell.length, 0);
  }

  /**
   * Ячейки охвата. Охват за пределами листа прижимается к крайним ячейкам: фигура, вылезшая за лист,
   * всё равно находится.
   */
  private cellRange(bounds: NormalizedBounds): [number, number, number, number] {
    const n = this.cellsPerSide;
    const cell = (value: number) => Math.min(n - 1, Math.max(0, Math.floor(value * n)));
    return [cell(bounds.minX), cell(bounds.minY), cell(bounds.maxX), cell(bounds.maxY)];
  }

  private link(entry: Entry<K>): void {
    for (let y = entry.y0; y <= entry.y1; y += 1) {
      for (let x = entry.x0; x <= entry.x1; x += 1) {
        this.cells[y * this.cellsPerSide + x]?.push(entry);
      }
    }
  }

  private unlink(entry: Entry<K>): void {
    for (let y = entry.y0; y <= entry.y1; y += 1) {
      for (let x = entry.x0; x <= entry.x1; x += 1) {
        const cell = this.cells[y * this.cellsPerSide + x];
        if (!cell) continue;
        const at = cell.indexOf(entry);
        if (at < 0) continue;
        // Порядок внутри ячейки не важен: снимаем перестановкой с последним, без сдвига массива.
        const last = cell.pop();
        if (last && at < cell.length) cell[at] = last;
      }
    }
  }
}
