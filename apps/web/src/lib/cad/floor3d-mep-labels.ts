/**
 * Русские подписи трасс и элементов ВИС для плашки 3D-вида этажа. Подтипы - по контракту
 * `cad_mep_routes3d.v2` (cad_mep.v15); незнакомый подтип показывается как есть, а не выдумывается.
 */

/** Вид полилинии (`kind`). */
export const ROUTE_KIND_LABELS: Readonly<Record<string, string>> = {
  riser: 'Стояк',
  route: 'Трасса',
  jumper: 'Перемычка',
  leadin: 'Подводка',
};

/** Источник Ø или сечения (`dn_source`); `null` - не определён (файлы до v15). */
export const DN_SOURCE_LABELS: Readonly<Record<string, string>> = {
  registry: 'по реестру',
  line: 'по линии',
  rule: 'по умолчанию',
};
export const DN_SOURCE_UNKNOWN = 'не определён';

export const FITTING_LABELS: Readonly<Record<string, string>> = {
  elbow: 'Отвод',
  tee: 'Тройник',
  cross: 'Крестовина',
  reducer: 'Переход',
  cleanout: 'Ревизия',
};

export const VALVE_LABELS: Readonly<Record<string, string>> = {
  ball_valve: 'Кран шаровой',
  filter: 'Фильтр',
  pressure_reducer: 'Регулятор давления',
  pressure_regulator: 'Регулятор давления',
  water_meter: 'Счётчик воды',
  check_valve: 'Обратный клапан',
  heat_meter: 'Теплосчётчик',
  balancing_valve: 'Балансировочный клапан',
  pk_valve: 'Клапан ПК',
  gate_valve: 'Затвор',
  flow_switch: 'Сигнализатор потока',
  fire_damper: 'ОЗК',
  smoke_damper: 'Клапан дымоудаления',
};

export const SLEEVE_LABELS: Readonly<Record<string, string>> = {
  wall: 'Гильза в стене',
  slab: 'Гильза в перекрытии',
};

export const TERMINAL_LABELS: Readonly<Record<string, string>> = {
  wc: 'Унитаз',
  washbasin: 'Умывальник',
  bath: 'Ванна',
  shower: 'Душ',
  kitchen_sink: 'Мойка',
  washer: 'Стиральная машина',
  floor_drain: 'Трап',
  convector: 'Конвектор',
  sprinkler: 'Ороситель',
  pk_cabinet: 'Шкаф ПК',
  grille: 'Решётка',
  ac_unit: 'Внутренний блок кондиционера',
  ac_inlet: 'Ввод фреона',
};

const ELEMENT_LABELS: Readonly<Record<string, { readonly labels: Readonly<Record<string, string>>; readonly fallback: string }>> = {
  fitting: { labels: FITTING_LABELS, fallback: 'Фасонина' },
  valve: { labels: VALVE_LABELS, fallback: 'Арматура' },
  sleeve: { labels: SLEEVE_LABELS, fallback: 'Гильза' },
  terminal: { labels: TERMINAL_LABELS, fallback: 'Прибор' },
};

/** Название элемента по-русски: «Тройник», «Кран шаровой», «Гильза в стене», «Унитаз». */
export const mepElementTitle = (type: string, subtype: string): string => {
  const entry = ELEMENT_LABELS[type];
  if (entry === undefined) return subtype;
  return entry.labels[subtype] ?? `${entry.fallback} (${subtype})`;
};
