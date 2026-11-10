/**
 * Группировка слоёв DXF по типу для панели «Слои».
 *
 * Тип определяется по подстроке имени слоя без учёта регистра (латиница и кириллица, «ё» = «е»).
 * Первое совпадение по порядку групп побеждает: «DOOR_OPENING» - дверь, а не проём. Слои контроля
 * качества (`QA_…`) - маркеры движка, а не элементы здания: они всегда в «Прочее».
 */

export interface ILayerGroup {
  readonly key: string;
  readonly label: string;
  /** Индексы слоёв в исходном списке, по возрастанию. */
  readonly indices: readonly number[];
}

interface IGroupRule {
  readonly key: string;
  readonly label: string;
  readonly patterns: readonly string[];
}

/** Порядок правил - порядок групп в панели и приоритет при совпадении. */
const RULES: readonly IGroupRule[] = [
  {
    key: 'walls',
    label: 'Стены',
    patterns: ['wall', 'стен', 'кладк', 'перегород'],
  },
  { key: 'doors', label: 'Двери', patterns: ['door', 'двер', 'ворот'] },
  { key: 'windows', label: 'Окна', patterns: ['wind', 'окн', 'окон'] },
  { key: 'openings', label: 'Проёмы', patterns: ['open', 'проем'] },
  { key: 'columns', label: 'Колонны', patterns: ['col', 'колон', 'монолит'] },
  { key: 'stairs', label: 'Лестницы', patterns: ['stair', 'лестн'] },
  { key: 'rooms', label: 'Помещения', patterns: ['room', 'space', 'помещ'] },
  { key: 'axes', label: 'Оси', patterns: ['axis', 'grid', 'оси', 'ось'] },
  { key: 'dimensions', label: 'Размеры', patterns: ['dim', 'разм'] },
  { key: 'texts', label: 'Тексты', patterns: ['text', 'txt', 'текст', 'anno'] },
  { key: 'hatches', label: 'Штриховка', patterns: ['hatch', 'штрих', 'fill'] },
];

const OTHER: Pick<IGroupRule, 'key' | 'label'> = { key: 'other', label: 'Прочее' };

const QA_PREFIX = /^qa[_\-\s]/;

const normalize = (name: string): string => name.toLowerCase().replace(/ё/g, 'е');

const keyOf = (name: string): string => {
  const value = normalize(name);
  if (QA_PREFIX.test(value)) return OTHER.key;
  const rule = RULES.find((item) => item.patterns.some((pattern) => value.includes(pattern)));
  return rule?.key ?? OTHER.key;
};

/** Слои по группам в порядке правил, «Прочее» - последним; пустые группы не возвращаются. */
export const groupLayers = (names: readonly string[]): ILayerGroup[] => {
  const buckets = new Map<string, number[]>();
  names.forEach((name, index) => {
    const key = keyOf(name);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(index);
    else buckets.set(key, [index]);
  });
  return [...RULES, OTHER].flatMap((rule) => {
    const indices = buckets.get(rule.key);
    return indices ? [{ key: rule.key, label: rule.label, indices }] : [];
  });
};
