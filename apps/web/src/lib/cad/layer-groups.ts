import { isMonolithLayer, isServiceLayer } from './layer-categories';

/**
 * Группировка слоёв DXF по типу для панели «Слои».
 *
 * Группы - только конструктив. Тип определяется по подстроке имени слоя без учёта регистра
 * (латиница и кириллица, «ё» = «е»); первое совпадение по порядку групп побеждает. Служебные слои
 * (`AUX_…`, `QA_…`) и `02_МОНОЛИТ…` (им управляют строки «Монолит» в блоке «Конструкции листа»)
 * в группы не попадают. Слой без совпадения - в «Прочее».
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
    label: 'Кладка и перегородки',
    patterns: ['wall', 'стен', 'кладк', 'перегород'],
  },
  { key: 'doors', label: 'Двери и ворота', patterns: ['door', 'двер', 'ворот'] },
  { key: 'windows', label: 'Окна', patterns: ['wind', 'окн', 'окон'] },
  { key: 'shafts', label: 'Шахты', patterns: ['shaft', 'шахт'] },
  { key: 'insulation', label: 'Утеплитель', patterns: ['insul', 'утепл'] },
];

const OTHER: Pick<IGroupRule, 'key' | 'label'> = { key: 'other', label: 'Прочее' };

const normalize = (name: string): string => name.toLowerCase().replace(/ё/g, 'е');

const keyOf = (name: string): string => {
  const value = normalize(name);
  const rule = RULES.find((item) => item.patterns.some((pattern) => value.includes(pattern)));
  return rule?.key ?? OTHER.key;
};

/** Слои по группам в порядке правил, «Прочее» - последним; пустые группы не возвращаются. */
export const groupLayers = (names: readonly string[]): ILayerGroup[] => {
  const buckets = new Map<string, number[]>();
  names.forEach((name, index) => {
    if (isServiceLayer(name) || isMonolithLayer(name)) return;
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
