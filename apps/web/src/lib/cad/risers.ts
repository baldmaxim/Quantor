import type {
  CadRiserEntry,
  RiserRole,
  RiserServes,
  RiserSystem,
  RiserValve,
} from '@quantor/api-client';

/**
 * Реестр стояков листа по проекту ИОС (ADR-0041): строки формы и их проверка. Правила совпадают
 * с контрактом `cad_risers.v1` на сервере; сервер проверяет их повторно.
 */

export const RISER_SYSTEMS: readonly RiserSystem[] = [
  'V1',
  'T3',
  'T4',
  'VPV',
  'AUP',
  'FS',
  'K1',
  'K2',
  'K4',
  'DRK',
  'VZH',
  'MO',
  'VMOP',
  'PMOP',
  'DU',
  'KDU',
  'DP',
  'TRV',
];
export const RISER_ROLES: readonly RiserRole[] = ['own', 'transit'];

export const RISER_SYSTEM_LABELS: Record<RiserSystem, string> = {
  V1: 'В1 ХВС',
  T3: 'Т3 ГВС',
  T4: 'Т4 циркуляция',
  VPV: 'ВПВ',
  AUP: 'АУП',
  FS: 'Сухотруб',
  K1: 'К1 канализация',
  K2: 'К2 водосток',
  K4: 'К4 дренаж',
  DRK: 'Дренаж кондиционеров',
  VZH: 'Вытяжка квартир',
  MO: 'Местный отсос',
  VMOP: 'Вытяжка МОП',
  PMOP: 'Приток МОП',
  DU: 'Дымоудаление',
  KDU: 'Компенсация ДУ',
  DP: 'Подпор',
  TRV: 'Транзитный канал',
};

/** Группы списка систем: подпись и состав. */
export const RISER_SYSTEM_GROUPS: readonly {
  readonly label: string;
  readonly systems: readonly RiserSystem[];
}[] = [
  { label: 'Вода и пожаротушение', systems: ['V1', 'T3', 'T4', 'VPV', 'AUP', 'FS'] },
  { label: 'Канализация и дренаж', systems: ['K1', 'K2', 'K4', 'DRK'] },
  { label: 'Вентиляция', systems: ['VZH', 'MO', 'VMOP', 'PMOP'] },
  { label: 'Противодымная', systems: ['DU', 'KDU', 'DP', 'TRV'] },
];

/** Воздушные системы: вместо Ø трубы - сечение или Ø канала. */
const AIR_SYSTEMS: ReadonlySet<RiserSystem> = new Set<RiserSystem>([
  'VZH',
  'MO',
  'VMOP',
  'PMOP',
  'DU',
  'KDU',
  'DP',
  'TRV',
]);
export const isAirSystem = (system: RiserSystem): boolean => AIR_SYSTEMS.has(system);

export const RISER_SERVES: readonly RiserServes[] = [
  'apartments',
  'corridor',
  'lobby_pbz',
  'tambour',
  'stair',
  'lift',
  'parking',
];
export const RISER_SERVES_LABELS: Record<RiserServes, string> = {
  apartments: 'Квартиры',
  corridor: 'Коридор',
  lobby_pbz: 'Лифтовой холл (ПБЗ)',
  tambour: 'Тамбур-шлюз',
  stair: 'Лестница',
  lift: 'Шахта лифта',
  parking: 'Автостоянка',
};

export const RISER_VALVES: readonly RiserValve[] = ['NO', 'NZ', 'none'];
export const RISER_VALVE_LABELS: Record<RiserValve, string> = {
  none: 'Без клапана',
  NO: 'НО',
  NZ: 'НЗ',
};

/** Форма канала воздушной системы: прямоугольное сечение a×b или круглый Ø. */
export type ChannelShape = 'section' | 'round';

export const RISER_ROLE_LABELS: Record<RiserRole, string> = {
  own: 'Своя',
  transit: 'Транзит',
};

export const MAX_RISERS = 120;
export const MARK_MAX = 32;
export const TEXT_MAX = 200;
export const DN_MIN_MM = 10;
export const DN_MAX_MM = 400;
export const COUNT_MAX = 8;
export const SECTION_MIN_MM = 50;
export const SECTION_MAX_MM = 3000;
export const CHANNEL_D_MIN_MM = 50;
export const CHANNEL_D_MAX_MM = 2000;
export const FLOOR_MIN = -10;
export const FLOOR_MAX = 200;
export const EI_MAX = 16;
const SHAFT_ID = /^S\d{2,3}$/;

/** Строка формы: числа и необязательные поля - текстом, как в полях ввода. */
export interface IRiserDraft {
  /** Ключ строки в списке интерфейса; на сервер не уходит. */
  readonly key: string;
  readonly system: RiserSystem;
  readonly mark: string;
  readonly dn: string;
  readonly role: RiserRole;
  readonly count: string;
  readonly shaftId: string;
  readonly source: string;
  /** Канал воздушной системы: форма и размеры (мм) - только у воздушных систем. */
  readonly channelShape: ChannelShape;
  readonly sectionA: string;
  readonly sectionB: string;
  readonly channelD: string;
  /** Этажи от-до, включительно. */
  readonly floorFrom: string;
  readonly floorTo: string;
  /** Пустая строка - не задано. */
  readonly serves: RiserServes | '';
  readonly valve: RiserValve | '';
  readonly ei: string;
  /** Примечание записи в форме не правится, но при сохранении не теряется. */
  readonly note: string | null;
}

export interface IRiserProblems {
  readonly mark?: string;
  readonly dn?: string;
  readonly count?: string;
  readonly shaftId?: string;
  readonly source?: string;
  readonly section?: string;
  readonly channelD?: string;
  readonly floors?: string;
  readonly ei?: string;
}

let nextKey = 0;
export const newRiserKey = (): string => {
  nextKey += 1;
  return `riser-${nextKey}`;
};

export const emptyRiser = (): IRiserDraft => ({
  key: newRiserKey(),
  system: 'V1',
  mark: '',
  dn: '',
  role: 'own',
  count: '1',
  shaftId: '',
  source: '',
  channelShape: 'section',
  sectionA: '',
  sectionB: '',
  channelD: '',
  floorFrom: '',
  floorTo: '',
  serves: '',
  valve: '',
  ei: '',
  note: null,
});

export const draftOf = (entry: CadRiserEntry): IRiserDraft => ({
  key: newRiserKey(),
  system: entry.system,
  mark: entry.mark,
  dn: entry.dn_mm == null ? '' : String(entry.dn_mm),
  role: entry.role,
  count: String(entry.count ?? 1),
  shaftId: entry.shaft_id ?? '',
  source: entry.source ?? '',
  channelShape: entry.d_mm == null ? 'section' : 'round',
  sectionA: entry.section_mm ? String(entry.section_mm[0]) : '',
  sectionB: entry.section_mm ? String(entry.section_mm[1]) : '',
  channelD: entry.d_mm == null ? '' : String(entry.d_mm),
  floorFrom: entry.floors ? String(entry.floors[0]) : '',
  floorTo: entry.floors ? String(entry.floors[1]) : '',
  serves: entry.serves ?? '',
  valve: entry.valve ?? '',
  ei: entry.ei ?? '',
  note: entry.note ?? null,
});

const INTEGER = /^\d+$/;
const SIGNED_INTEGER = /^-?\d+$/;

const inRange = (text: string, min: number, max: number, pattern = INTEGER): boolean =>
  pattern.test(text) && Number(text) >= min && Number(text) <= max;

export const riserProblems = (draft: IRiserDraft): IRiserProblems => {
  const problems: { -readonly [K in keyof IRiserProblems]: IRiserProblems[K] } = {};
  const mark = draft.mark.trim();
  if (mark === '') problems.mark = 'Укажите марку.';
  else if (mark.length > MARK_MAX) problems.mark = `Не длиннее ${MARK_MAX} знаков.`;
  const dn = draft.dn.trim();
  const air = isAirSystem(draft.system);
  if (air && dn !== '')
    problems.dn = 'У воздушной системы нет Ø трубы: задайте сечение или Ø канала.';
  else if (dn !== '' && !inRange(dn, DN_MIN_MM, DN_MAX_MM)) {
    problems.dn = `От ${DN_MIN_MM} до ${DN_MAX_MM} мм.`;
  }
  const a = draft.sectionA.trim();
  const b = draft.sectionB.trim();
  const d = draft.channelD.trim();
  if (!air) {
    // У трубной системы канала нет; поля скрыты и при смене системы очищаются.
    if (a !== '' || b !== '' || d !== '') {
      problems.section = 'У трубной системы нет канала: задайте Ø трубы.';
    }
  } else if (draft.channelShape === 'section') {
    if (a !== '' || b !== '') {
      if (
        !inRange(a, SECTION_MIN_MM, SECTION_MAX_MM) ||
        !inRange(b, SECTION_MIN_MM, SECTION_MAX_MM)
      ) {
        problems.section = `Оба размера - от ${SECTION_MIN_MM} до ${SECTION_MAX_MM} мм.`;
      }
    }
  } else if (d !== '' && !inRange(d, CHANNEL_D_MIN_MM, CHANNEL_D_MAX_MM)) {
    problems.channelD = `От ${CHANNEL_D_MIN_MM} до ${CHANNEL_D_MAX_MM} мм.`;
  }
  const from = draft.floorFrom.trim();
  const to = draft.floorTo.trim();
  if (from !== '' || to !== '') {
    if (
      !inRange(from, FLOOR_MIN, FLOOR_MAX, SIGNED_INTEGER) ||
      !inRange(to, FLOOR_MIN, FLOOR_MAX, SIGNED_INTEGER)
    ) {
      problems.floors = `Оба этажа - целые от ${FLOOR_MIN} до ${FLOOR_MAX}.`;
    } else if (Number(from) > Number(to)) {
      problems.floors = 'Этаж «от» больше этажа «до».';
    }
  }
  if (draft.ei.trim().length > EI_MAX) problems.ei = `Не длиннее ${EI_MAX} знаков.`;
  const count = draft.count.trim();
  if (!INTEGER.test(count) || Number(count) < 1 || Number(count) > COUNT_MAX) {
    problems.count = `От 1 до ${COUNT_MAX}.`;
  }
  const shaft = draft.shaftId.trim();
  if (shaft !== '' && !SHAFT_ID.test(shaft)) problems.shaftId = 'Вид S12 или S123.';
  if (draft.source.trim().length > TEXT_MAX) problems.source = `Не длиннее ${TEXT_MAX} знаков.`;
  return problems;
};

export const hasProblems = (problems: IRiserProblems): boolean => Object.keys(problems).length > 0;

const orNull = (value: string): string | null => value.trim() || null;

/**
 * Запись контракта из строки формы; строка должна пройти `riserProblems`. Поля cad_mep.v10
 * (канал, этажи, назначение, клапан, EI) попадают в запись только заданные.
 */
export const entryOf = (draft: IRiserDraft): CadRiserEntry => {
  const air = isAirSystem(draft.system);
  const a = draft.sectionA.trim();
  const b = draft.sectionB.trim();
  const d = draft.channelD.trim();
  const from = draft.floorFrom.trim();
  const to = draft.floorTo.trim();
  const ei = draft.ei.trim();
  const entry: CadRiserEntry = {
    system: draft.system,
    mark: draft.mark.trim(),
    dn_mm: air || draft.dn.trim() === '' ? null : Number(draft.dn),
    role: draft.role,
    count: Number(draft.count),
    shaft_id: orNull(draft.shaftId),
    source: orNull(draft.source),
    note: draft.note,
  };
  if (air && draft.channelShape === 'section' && a !== '' && b !== '') {
    entry.section_mm = [Number(a), Number(b)];
  }
  if (air && draft.channelShape === 'round' && d !== '') entry.d_mm = Number(d);
  if (from !== '' && to !== '') entry.floors = [Number(from), Number(to)];
  if (draft.serves !== '') entry.serves = draft.serves;
  if (draft.valve !== '') entry.valve = draft.valve;
  if (ei !== '') entry.ei = ei;
  return entry;
};

/** Содержимое строк без служебных ключей: так сравнивают «изменено ли». */
export const serializeDrafts = (drafts: readonly IRiserDraft[]): string =>
  JSON.stringify(
    drafts.map((draft) => [
      draft.system,
      draft.mark.trim(),
      draft.dn.trim(),
      draft.role,
      draft.count.trim(),
      draft.shaftId.trim(),
      draft.source.trim(),
      draft.channelShape,
      draft.sectionA.trim(),
      draft.sectionB.trim(),
      draft.channelD.trim(),
      draft.floorFrom.trim(),
      draft.floorTo.trim(),
      draft.serves,
      draft.valve,
      draft.ei.trim(),
      draft.note,
    ]),
  );

/** Заполнены ли поля блока «Подробнее» (этажи, назначение, клапан, EI). */
export const hasDetails = (draft: IRiserDraft): boolean =>
  draft.floorFrom.trim() !== '' ||
  draft.floorTo.trim() !== '' ||
  draft.serves !== '' ||
  draft.valve !== '' ||
  draft.ei.trim() !== '';

/**
 * Смена системы: поля другого вида системы очищаются (у трубной нет канала, у воздушной нет Ø трубы).
 */
export const systemPatch = (draft: IRiserDraft, system: RiserSystem): Partial<IRiserDraft> => {
  if (isAirSystem(system) === isAirSystem(draft.system)) return { system };
  return isAirSystem(system)
    ? { system, dn: '' }
    : { system, channelShape: 'section', sectionA: '', sectionB: '', channelD: '' };
};
