import type { CadRiserEntry, RiserRole, RiserSystem } from '@quantor/api-client';

/**
 * Реестр стояков листа по проекту ИОС (ADR-0041): строки формы и их проверка. Правила совпадают
 * с контрактом `cad_risers.v1` на сервере; сервер проверяет их повторно.
 */

export const RISER_SYSTEMS: readonly RiserSystem[] = ['V1', 'T3', 'T4', 'VPV', 'AUP', 'FS'];
export const RISER_ROLES: readonly RiserRole[] = ['own', 'transit'];

export const RISER_SYSTEM_LABELS: Record<RiserSystem, string> = {
  V1: 'В1 холодная вода',
  T3: 'Т3 горячая вода',
  T4: 'Т4 циркуляция',
  VPV: 'ВПВ',
  AUP: 'АУП',
  FS: 'Пожарный стояк',
};

export const RISER_ROLE_LABELS: Record<RiserRole, string> = {
  own: 'Своя',
  transit: 'Транзит',
};

export const MAX_RISERS = 40;
export const MARK_MAX = 32;
export const TEXT_MAX = 200;
export const DN_MIN_MM = 10;
export const DN_MAX_MM = 400;
export const COUNT_MAX = 8;
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
  /** Примечание записи в форме не правится, но при сохранении не теряется. */
  readonly note: string | null;
}

export interface IRiserProblems {
  readonly mark?: string;
  readonly dn?: string;
  readonly count?: string;
  readonly shaftId?: string;
  readonly source?: string;
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
  note: entry.note ?? null,
});

const INTEGER = /^\d+$/;

export const riserProblems = (draft: IRiserDraft): IRiserProblems => {
  const problems: { -readonly [K in keyof IRiserProblems]: IRiserProblems[K] } = {};
  const mark = draft.mark.trim();
  if (mark === '') problems.mark = 'Укажите марку.';
  else if (mark.length > MARK_MAX) problems.mark = `Не длиннее ${MARK_MAX} знаков.`;
  const dn = draft.dn.trim();
  if (dn !== '' && (!INTEGER.test(dn) || Number(dn) < DN_MIN_MM || Number(dn) > DN_MAX_MM)) {
    problems.dn = `От ${DN_MIN_MM} до ${DN_MAX_MM} мм.`;
  }
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

/** Запись контракта из строки формы; строка должна пройти `riserProblems`. */
export const entryOf = (draft: IRiserDraft): CadRiserEntry => ({
  system: draft.system,
  mark: draft.mark.trim(),
  dn_mm: draft.dn.trim() === '' ? null : Number(draft.dn),
  role: draft.role,
  count: Number(draft.count),
  shaft_id: orNull(draft.shaftId),
  source: orNull(draft.source),
  note: draft.note,
});

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
      draft.note,
    ]),
  );
