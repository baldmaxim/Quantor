/** Размер области просмотра в пикселях (clientWidth / clientHeight). */
export interface IHostSize {
  width: number;
  height: number;
}

/** Что делать с видом при очередном размере области. */
export type FitAction = 'fit' | 'defer' | 'keep';

/** Область можно мерить только при ненулевых сторонах: скрытый контейнер (`hidden`) даёт 0x0. */
export const isMeasurable = ({ width, height }: IHostSize): boolean => width > 0 && height > 0;

/**
 * Решает, вписывать ли лист при новом размере области.
 *
 * - `fit`: лист ждёт вписки и область впервые получила размер, либо вписка нужна сейчас;
 * - `defer`: лист ждёт вписки, а область по-прежнему нулевая - вписывать нельзя (получился бы
 *   минимальный масштаб), ждём первого ненулевого размера;
 * - `keep`: лист уже вписан, обычный ресайз - вид не пересчитывается, только компенсируется сдвиг.
 */
export const decideFit = (size: IHostSize, fitPending: boolean): FitAction => {
  if (!fitPending) return 'keep';
  return isMeasurable(size) ? 'fit' : 'defer';
};
