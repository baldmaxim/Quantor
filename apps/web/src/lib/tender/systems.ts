/**
 * Разделы и системы расчётов TENDER (формат `quantor.tender_calc.v1`, ADR-0051).
 *
 * Словарь закрыт форматом: код системы приходит строкой, поэтому незнакомый код (новая версия формата)
 * не ломает экран — подпись берётся из самого кода, цвет — нейтральный.
 */

export type TenderDiscipline = 'mech' | 'eom' | 'ss';

export const DISCIPLINE_ORDER: readonly TenderDiscipline[] = ['mech', 'eom', 'ss'];

export const DISCIPLINE_LABELS: Readonly<Record<TenderDiscipline, string>> = {
  mech: 'Механика',
  eom: 'ЭОМ',
  ss: 'СС',
};

export const SYSTEM_LABELS: Readonly<Record<string, string>> = {
  // mech
  heating: 'Отопление',
  water_supply: 'Водоснабжение',
  sewage: 'Канализация',
  storm_drain: 'Водостоки',
  fire_sprinkler: 'АУП',
  fire_hydrant: 'Внутренний противопожарный водопровод',
  dry_pipe: 'Сухотрубы',
  ventilation: 'Вентиляция',
  smoke_control: 'Дымоудаление и подпор',
  conditioning: 'Кондиционирование',
  cooling: 'Холодоснабжение',
  itp: 'ИТП',
  mech_other: 'Механика, прочее',
  // eom
  power: 'Силовое электрооборудование',
  lighting: 'Электрическое освещение',
  grounding: 'Заземление',
  lightning: 'Молниезащита',
  eom_other: 'ЭОМ, прочее',
  // ss
  ss_network: 'Сети связи',
  ss_security: 'Охранная сигнализация и видеонаблюдение',
  ss_fire_alarm: 'Пожарная сигнализация',
  ss_dispatch: 'Диспетчеризация',
  ss_other: 'СС, прочее',
};

/** Подпись системы по-русски; неизвестный код показывается как есть. */
export const systemLabel = (system: string): string => SYSTEM_LABELS[system] ?? system;

export const disciplineLabel = (discipline: string): string =>
  (DISCIPLINE_LABELS as Readonly<Record<string, string>>)[discipline] ?? discipline;

/** Токен цвета системы для неизвестного кода: тот же нейтральный, что у «прочего». */
const FALLBACK_COLOR_TOKEN = '--cad-mep-node';

/**
 * Имя CSS-переменной цвета системы (`--tender-sys-heating`; `_` -> `-`). Переменные заведены в
 * `packages/ui/src/base.css` для обеих тем. Использование: `var(${systemColorToken(code)})`.
 */
export const systemColorToken = (system: string): string =>
  system in SYSTEM_LABELS ? `--tender-sys-${system.replace(/_/g, '-')}` : FALLBACK_COLOR_TOKEN;
