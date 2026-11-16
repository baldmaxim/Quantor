/**
 * Ограничитель одновременных запросов: лишние ждут очереди. Нужен ленивой загрузке видов расчётов в
 * 3D здания, где видов много, а канал один.
 */
export interface ILimiter {
  readonly run: <T>(task: () => Promise<T>) => Promise<T>;
}

export const createLimiter = (limit: number): ILimiter => {
  let active = 0;
  const queue: (() => void)[] = [];
  const next = (): void => {
    if (active >= limit) return;
    const start = queue.shift();
    if (start === undefined) return;
    active += 1;
    start();
  };
  return {
    run: <T>(task: () => Promise<T>): Promise<T> =>
      new Promise<T>((resolve, reject) => {
        queue.push(() => {
          task()
            .then(resolve, reject)
            .finally(() => {
              active -= 1;
              next();
            });
        });
        next();
      }),
  };
};
