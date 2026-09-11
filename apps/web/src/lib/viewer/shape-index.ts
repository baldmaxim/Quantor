/**
 * Индекс фигур листа поверх общего `GridIndex` (промт 04): сейчас измерений, дальше — AI-кандидатов.
 *
 * Хранит охваты в нормализованных координатах и порядок фигур в списке. Порядок нужен двоим:
 * отрисовке — поздние фигуры лежат поверх ранних, и попаданию — из фигур одного охвата побеждает
 * первая, как при линейном переборе. Индекс только сужает круг кандидатов: точная проверка
 * геометрии остаётся прежней.
 *
 * Ключ — `id` фигуры, и он обязан быть уникален в списке: у измерений это ключ базы.
 */

import type { NormalizedPoint } from './coordinates';
import { GridIndex, type NormalizedBounds } from './spatial-index';

/** То, что индексу нужно от фигуры: ключ и точки. */
export interface IndexedShape {
  readonly id: string;
  readonly points: readonly NormalizedPoint[];
}

export interface IndexedHit<T extends IndexedShape> {
  readonly item: T;
  /** Место в списке, по которому индекс синхронизирован. */
  readonly order: number;
}

/** Охват точек. У пустого списка — неконечный: такую фигуру индекс не отдаёт. */
export const boundsOfPoints = (points: readonly NormalizedPoint[]): NormalizedBounds => {
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const point of points) {
    if (point.x < minX) minX = point.x;
    if (point.x > maxX) maxX = point.x;
    if (point.y < minY) minY = point.y;
    if (point.y > maxY) maxY = point.y;
  }
  return { minX, minY, maxX, maxY };
};

const samePoints = (a: readonly NormalizedPoint[], b: readonly NormalizedPoint[]): boolean =>
  a === b ||
  (a.length === b.length &&
    a.every((point, index) => point.x === b[index]?.x && point.y === b[index]?.y));

interface Entry<T> {
  item: T;
  order: number;
  /** Номер последней синхронизации, в списке которой фигура была. */
  generation: number;
}

export class ShapeIndex<T extends IndexedShape> {
  private readonly grid = new GridIndex<string>();
  private readonly entries = new Map<string, Entry<T>>();
  private synced: readonly T[] | null = null;
  private generation = 0;

  /** Число фигур в индексе. */
  get size(): number {
    return this.entries.size;
  }

  /**
   * Приводит индекс к списку без перестройки: новые фигуры вставляются, изменённые переносятся,
   * исчезнувшие удаляются. Тот же массив — ничего не делает.
   *
   * Неизменённая фигура узнаётся по ссылке, а при новой ссылке — по точкам: кэш запросов отдаёт
   * после правки новый список, в котором прочие измерения те же объекты.
   */
  sync(items: readonly T[]): void {
    if (items === this.synced) return;

    // Поколение синхронизации вместо множества увиденных ключей: на 25 000 фигур правка одного
    // измерения не должна выделять память на каждую фигуру.
    this.generation += 1;
    const generation = this.generation;
    items.forEach((item, order) => {
      const previous = this.entries.get(item.id);
      if (!previous) {
        this.grid.set(item.id, boundsOfPoints(item.points));
        this.entries.set(item.id, { item, order, generation });
        return;
      }
      if (previous.item !== item && !samePoints(previous.item.points, item.points)) {
        this.grid.set(item.id, boundsOfPoints(item.points));
      }
      previous.item = item;
      previous.order = order;
      previous.generation = generation;
    });
    for (const [id, entry] of this.entries) {
      if (entry.generation === generation) continue;
      this.entries.delete(id);
      this.grid.delete(id);
    }
    this.synced = items;
  }

  /** Сколько ссылок лежит в ячейках сетки — для оценки памяти в замере. */
  cellReferences(): number {
    return this.grid.cellReferences();
  }

  /** Место фигуры в списке или `null`, если её нет. */
  orderOf(id: string): number | null {
    return this.entries.get(id)?.order ?? null;
  }

  /** Фигуры, чей охват пересекает хоть один прямоугольник, в порядке списка. */
  query(areas: readonly NormalizedBounds[]): IndexedHit<T>[] {
    const keys = new Set<string>();
    for (const area of areas) {
      for (const key of this.grid.search(area)) keys.add(key);
    }

    const hits: IndexedHit<T>[] = [];
    for (const key of keys) {
      const entry = this.entries.get(key);
      if (entry) hits.push({ item: entry.item, order: entry.order });
    }
    return hits.sort((a, b) => a.order - b.order);
  }
}
