import type {
  DocAnswerOut,
  DocCandidateOut,
  DocQuestionOut,
  PutDocAnswerData,
} from '@quantor/api-client';

/**
 * Вопросы к документации (ADR-0043, шаг 2, В4): подписи, область, ссылка на лист и сборка
 * ручного ответа. «Нет в проекте» и пустое значение никогда не превращаются в 0.
 */

export type DocAnswerBody = PutDocAnswerData['body'];

export const SOURCE_LABELS: Record<DocAnswerOut['source'], string> = {
  document: 'Документация',
  manual: 'Вручную',
  norm_assumption: 'Норматив (допущение)',
  not_in_project: 'Нет в проекте',
};

export const NOT_IN_PROJECT_TEXT = 'Нет в проекте';
export const WHOLE_PROJECT_TEXT = 'весь проект';

export const sourceLabel = (source: DocAnswerOut['source']): string => SOURCE_LABELS[source];

/** Область ответа: корпус и секция; пусто в обоих — весь проект. */
export const scopeText = (building: string | null, section: string | null): string => {
  const parts: string[] = [];
  if (building) parts.push(`корпус ${building}`);
  if (section) parts.push(`секция ${section}`);
  return parts.length ? parts.join(', ') : WHOLE_PROJECT_TEXT;
};

/** Значение ответа для показа: `display`, иначе текст; «нет в проекте» — словами, не числом. */
export const answerValueText = (answer: DocAnswerOut): string => {
  if (answer.source === 'not_in_project') return NOT_IN_PROJECT_TEXT;
  return answer.value?.display || answer.value_text || '—';
};

/** Место кандидата в комплекте: корпус, секция, уровень. */
export const candidatePlace = (candidate: DocCandidateOut): string | null => {
  const parts: string[] = [];
  if (candidate.building) parts.push(`корпус ${candidate.building}`);
  if (candidate.section) parts.push(`секция ${candidate.section}`);
  if (candidate.level) parts.push(`уровень ${candidate.level}`);
  return parts.length ? parts.join(', ') : null;
};

/** Страница для человека: подпись листа либо номер с 1. */
export const pageText = (pageIndex: number, pageLabel: string | null): string =>
  pageLabel ? `${pageLabel} (стр. ${pageIndex + 1})` : `стр. ${pageIndex + 1}`;

/**
 * Ссылка на страницу документа в рабочей области: `page` — номер с 1, как и в остальном
 * интерфейсе (см. `documentHref` в `components/calc/FactEvidence.tsx`).
 */
export const docPageHref = (projectId: string, revisionId: string, pageIndex: number): string =>
  `/projects/${projectId}/workspace?revision=${revisionId}&page=${pageIndex + 1}`;

/** Тело принятия кандидата: область берёт сервер из самого кандидата. */
export const acceptCandidateBody = (candidateId: string): DocAnswerBody => ({
  source: 'document',
  candidate_id: candidateId,
});

export const normAssumptionBody = (): DocAnswerBody => ({ source: 'norm_assumption' });

export const notInProjectBody = (note: string): DocAnswerBody => {
  const trimmed = note.trim();
  return trimmed ? { source: 'not_in_project', note: trimmed } : { source: 'not_in_project' };
};

/* ------------------------------------------------------------------ ручной ввод */

export const ROUND_CODE = 'round';
export const ROSETTE_OPTIONS = [
  { code: 'rosette_down', label: 'Розеткой вниз' },
  { code: 'rosette_up', label: 'Розеткой вверх' },
] as const;

export type Qualifier = 'min' | 'max' | '';

export interface IManualForm {
  readonly text: string;
  /** Поля чисел в мм: сколько их и какие обязательны — по виду вопроса. */
  readonly numbers: readonly string[];
  readonly qualifier: Qualifier;
  readonly round: boolean;
  readonly rosette: string;
  readonly note: string;
}

/** Описание полей ручного ввода по виду значения. */
export interface IManualLayout {
  readonly numberLabels: readonly string[];
  readonly requiredNumbers: number;
  readonly showText: boolean;
  readonly showQualifier: boolean;
  readonly showRound: boolean;
  readonly showRosette: boolean;
}

export const manualLayout = (
  question: Pick<DocQuestionOut, 'code' | 'value_kind'>,
): IManualLayout => {
  switch (question.value_kind) {
    case 'length_mm':
      return {
        numberLabels: ['Значение, мм'],
        requiredNumbers: 1,
        showText: false,
        showQualifier: true,
        showRound: false,
        showRosette: false,
      };
    case 'range_mm':
      return {
        numberLabels: ['От, мм', 'До, мм (необязательно)'],
        requiredNumbers: 1,
        showText: false,
        showQualifier: true,
        showRound: false,
        showRosette: false,
      };
    case 'section_mm':
      return {
        numberLabels: ['Ширина, мм', 'Высота, мм'],
        requiredNumbers: 2,
        showText: false,
        showQualifier: false,
        showRound: question.code === 'duct_section',
        showRosette: false,
      };
    case 'enum':
      return {
        numberLabels: [],
        requiredNumbers: 0,
        showText: false,
        showQualifier: false,
        showRound: false,
        showRosette: true,
      };
    default:
      return {
        numberLabels: ['Число, мм (необязательно)'],
        requiredNumbers: 0,
        showText: true,
        showQualifier: false,
        showRound: false,
        showRosette: false,
      };
  }
};

export const emptyManualForm = (layout: IManualLayout): IManualForm => ({
  text: '',
  numbers: layout.numberLabels.map(() => ''),
  qualifier: '',
  round: false,
  rosette: '',
  note: '',
});

export type ManualResult = { readonly body: DocAnswerBody } | { readonly error: string };

const parseMm = (raw: string): number | null => {
  const trimmed = raw.trim();
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null;
};

/** Ручной ответ: пояснение «откуда число» обязательно, числа — целые мм в границах каталога. */
export const buildManualAnswer = (
  question: Pick<DocQuestionOut, 'code' | 'value_kind' | 'min_mm' | 'max_mm'>,
  form: IManualForm,
): ManualResult => {
  const layout = manualLayout(question);
  const note = form.note.trim();
  if (!note) return { error: 'Укажите, откуда значение: документ, лист, расчёт.' };

  const round = layout.showRound && form.round;
  const fields = round ? form.numbers.slice(0, 1) : form.numbers;
  const numbers: number[] = [];
  for (const raw of fields) {
    if (!raw.trim()) continue;
    const parsed = parseMm(raw);
    if (parsed === null) return { error: 'Размеры — целые числа в миллиметрах.' };
    if (parsed < question.min_mm || parsed > question.max_mm) {
      return {
        error: `Размер ${parsed} мм вне допустимых ${question.min_mm}–${question.max_mm} мм.`,
      };
    }
    numbers.push(parsed);
  }
  const needed = round ? 1 : layout.requiredNumbers;
  if (fields.slice(0, needed).some((raw) => !raw.trim())) {
    return { error: 'Заполните обязательные размеры.' };
  }
  if (question.value_kind === 'range_mm' && numbers.length === 2 && numbers[0]! >= numbers[1]!) {
    return { error: 'В диапазоне «от» должно быть меньше «до».' };
  }

  let valueText = '';
  let code: string | null = null;
  if (layout.showText) {
    valueText = form.text.trim();
    if (!valueText) return { error: 'Введите значение.' };
  } else if (layout.showRosette) {
    const option = ROSETTE_OPTIONS.find((item) => item.code === form.rosette);
    if (!option) return { error: 'Выберите положение розетки.' };
    valueText = option.label;
    code = option.code;
  } else if (round) {
    valueText = `Ø${numbers[0]} мм`;
    code = ROUND_CODE;
  } else {
    const separator = question.value_kind === 'section_mm' ? '×' : '–';
    valueText = `${numbers.join(separator)} мм`;
  }

  const qualifier = layout.showQualifier && form.qualifier ? form.qualifier : null;
  if (qualifier) {
    valueText = `${qualifier === 'min' ? 'не менее' : 'не более'} ${valueText}`;
  }
  return {
    body: {
      source: 'manual',
      value_text: valueText,
      value: { numbers, qualifier, code },
      note,
    },
  };
};
