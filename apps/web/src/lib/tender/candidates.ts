import type { TenderBaseCandidateRead } from '@quantor/api-client';

/** Дерево кандидатов выпуска базы: корпус → секция → этажи (виды). */

export interface ISectionGroup {
  readonly key: string;
  readonly label: string;
  readonly floors: readonly TenderBaseCandidateRead[];
}

export interface ICorpsGroup {
  readonly key: string;
  readonly label: string;
  readonly sections: readonly ISectionGroup[];
}

const NO_CORPS = 'Без корпуса';
const NO_SECTION = 'Без секции';

const byNumber = (a: string, b: string): number => a.localeCompare(b, 'ru', { numeric: true });

/** Подпись этажа: подписи этажей плана (типовой план — несколько) или название листа. */
export const candidateTitle = (candidate: TenderBaseCandidateRead): string => {
  const floors = candidate.floors.length > 0 ? `Этажи ${candidate.floors.join(', ')}` : null;
  return floors ?? candidate.label;
};

export const groupCandidates = (
  candidates: readonly TenderBaseCandidateRead[],
): readonly ICorpsGroup[] => {
  const corpsMap = new Map<string, Map<string, TenderBaseCandidateRead[]>>();
  for (const candidate of candidates) {
    const corps = candidate.corps ?? NO_CORPS;
    const section = candidate.section ?? NO_SECTION;
    const sections = corpsMap.get(corps) ?? new Map<string, TenderBaseCandidateRead[]>();
    const floors = sections.get(section) ?? [];
    floors.push(candidate);
    sections.set(section, floors);
    corpsMap.set(corps, sections);
  }
  return [...corpsMap.entries()]
    .sort(([a], [b]) => byNumber(a, b))
    .map(([corps, sections]) => ({
      key: corps,
      label: corps === NO_CORPS ? corps : `Корпус ${corps}`,
      sections: [...sections.entries()]
        .sort(([a], [b]) => byNumber(a, b))
        .map(([section, floors]) => ({
          key: `${corps}|${section}`,
          label: section === NO_SECTION ? section : `Секция ${section}`,
          // Снизу вверх: по отметке пола, затем по ключу вида.
          floors: [...floors].sort(
            (a, b) => a.base_z_mm - b.base_z_mm || a.view_key.localeCompare(b.view_key),
          ),
        })),
    }));
};

/** Можно ли включить вид в выпуск: сервер принимает только готовые. */
export const isSelectable = (candidate: TenderBaseCandidateRead): boolean => candidate.ready;

/** По умолчанию отмечены готовые и совмещённые по осям виды. */
export const defaultSelection = (
  candidates: readonly TenderBaseCandidateRead[],
): ReadonlySet<string> =>
  new Set(
    candidates
      .filter((candidate) => candidate.ready && candidate.alignment !== 'none')
      .map((candidate) => candidate.view_key),
  );

/** Пометка вида в списке: почему он не отмечен или недоступен. */
export const candidateNote = (candidate: TenderBaseCandidateRead): string | null => {
  if (!candidate.ready) {
    return candidate.problems.length > 0 ? candidate.problems.join('; ') : 'нет кадра листа';
  }
  if (candidate.alignment === 'none') return 'не совмещён с осями здания';
  return null;
};
