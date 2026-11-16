/**
 * Открытые вкладки листов рабочей области.
 *
 * Вкладки живут в адресе (`?tabs=1,4,7`) рядом с активным листом (`?page=4`): ссылка открывает
 * тот же набор листов, что видел автор. Номер в обоих параметрах - позиция листа в ревизии,
 * с единицы. Активный лист в `tabs` может отсутствовать: тогда он дописывается в конец, так что
 * переход, не знающий о вкладках, не теряет ни уже открытые вкладки, ни сам лист.
 *
 * Обычный щелчок по листу заменяет активную вкладку, Ctrl + щелчок и средняя кнопка - открывают
 * лист в новой вкладке рядом с активной.
 */

/** Позиции листов из параметра адреса: целые, в пределах ревизии, без повторов, в исходном порядке. */
export const parseSheetTabs = (param: string | null, count: number): number[] => {
  if (!param || count <= 0) return [];
  const result: number[] = [];
  for (const part of param.split(',')) {
    const value = Number(part.trim());
    if (!Number.isInteger(value) || value < 1 || value > count) continue;
    if (!result.includes(value)) result.push(value);
  }
  return result;
};

/** Показываемые вкладки: из адреса и активный лист, если его там нет. */
export const openSheetTabs = (tabs: readonly number[], active: number | null): number[] =>
  active === null || tabs.includes(active) ? [...tabs] : [...tabs, active];

/**
 * Переход на лист в той же вкладке: уже открытый лист просто становится активным, иначе
 * он занимает место активной вкладки.
 */
export const replaceSheetTab = (tabs: readonly number[], active: number, next: number): number[] => {
  const open = openSheetTabs(tabs, active);
  if (open.includes(next)) return open;
  return open.map((value) => (value === active ? next : value));
};

/** Лист в новой вкладке - сразу справа от активной; уже открытый лист не дублируется. */
export const addSheetTab = (tabs: readonly number[], active: number, next: number): number[] => {
  const open = openSheetTabs(tabs, active);
  if (open.includes(next)) return open;
  const at = open.indexOf(active);
  return [...open.slice(0, at + 1), next, ...open.slice(at + 1)];
};

/**
 * Закрытие вкладки. Последнюю закрыть нельзя: лист в рабочей области открыт всегда.
 * Закрытая активная вкладка уступает место соседней справа, у крайней правой - слева.
 */
export const closeSheetTab = (
  tabs: readonly number[],
  active: number,
  target: number,
): { tabs: number[]; active: number } => {
  const open = openSheetTabs(tabs, active);
  const at = open.indexOf(target);
  if (at < 0 || open.length <= 1) return { tabs: open, active };
  const rest = open.filter((value) => value !== target);
  if (target !== active) return { tabs: rest, active };
  return { tabs: rest, active: rest[Math.min(at, rest.length - 1)] ?? active };
};

/** Значение параметра адреса: одна вкладка параметра не требует - её задаёт `page`. */
export const serializeSheetTabs = (tabs: readonly number[]): string | null =>
  tabs.length > 1 ? tabs.join(',') : null;

/** Открыть лист в новой вкладке: Ctrl (на macOS - Cmd) с щелчком или средняя кнопка мыши. */
export const opensInNewTab = (event: {
  readonly button: number;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
}): boolean => event.button === 1 || (event.button === 0 && (event.ctrlKey || event.metaKey));
