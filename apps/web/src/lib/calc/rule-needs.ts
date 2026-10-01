import type {
  CalcDecisionSource,
  CalcEngineeringSource,
  CalcNormativeSource,
  CalcRuleSummaryRead,
  CalcRuleType,
  CalcRuleVersionRead,
  CalcVkCalculatorRead,
  CalcVkRuleNeedRead,
  CalcVkRuleVersionCreate,
} from '@quantor/api-client';

/**
 * Решения инженера по заявкам калькуляторов ВК: чистые помощники формы, без запросов.
 *
 * Инженер вносит только тип правила, значения параметров, основание и ограничения. Контракт
 * реализации собирает сервер по заявке. Подходит ли основание к типу правила, окончательно
 * проверяет сервер при утверждении; здесь — только подсказка, какие основания годятся.
 */

export type SourceKind =
  'ENGINEERING_METHOD' | 'NORMATIVE_DOCUMENT' | 'REVIEWER_DECISION' | 'OWNER_DECISION';

type RuleSource = CalcEngineeringSource | CalcNormativeSource | CalcDecisionSource;

export const SOURCE_KIND_TITLES: Readonly<Record<SourceKind, string>> = {
  ENGINEERING_METHOD: 'Инженерная методика',
  NORMATIVE_DOCUMENT: 'Нормативный документ',
  REVIEWER_DECISION: 'Решение проверяющего инженера',
  OWNER_DECISION: 'Решение владельца',
};

/** Основания, которые сервер принимает для типа правила (validation.approval_problems). */
export const SOURCE_KINDS: Readonly<Record<CalcRuleType, readonly SourceKind[]>> = {
  ENGINEERING: ['ENGINEERING_METHOD'],
  NORMATIVE: ['NORMATIVE_DOCUMENT'],
  GEOMETRY: ['ENGINEERING_METHOD', 'REVIEWER_DECISION', 'NORMATIVE_DOCUMENT'],
  PHYSICS: ['ENGINEERING_METHOD', 'NORMATIVE_DOCUMENT'],
  TENDER_ASSUMPTION: ['OWNER_DECISION', 'REVIEWER_DECISION'],
  // Правилу производителя нужны производитель и линейка в области применения — форма их не
  // собирает, такую версию заводят через API реестра.
  MANUFACTURER: [],
};

export interface ISourceField {
  key: string;
  title: string;
  kind: 'text' | 'long' | 'date';
  optional?: boolean;
}

export const SOURCE_FIELDS: Readonly<Record<SourceKind, readonly ISourceField[]>> = {
  ENGINEERING_METHOD: [
    { key: 'title', title: 'Название методики', kind: 'text' },
    { key: 'author', title: 'Автор или организация', kind: 'text' },
    { key: 'reference', title: 'Где опубликована или хранится', kind: 'text' },
    { key: 'summary', title: 'Суть методики и ограничения', kind: 'long' },
  ],
  NORMATIVE_DOCUMENT: [
    { key: 'document_title', title: 'Название документа', kind: 'text' },
    { key: 'designation', title: 'Обозначение (например, СП 30.13330.2020)', kind: 'text' },
    { key: 'edition', title: 'Редакция или изменение', kind: 'text' },
    { key: 'clause', title: 'Пункт, раздел, таблица', kind: 'text' },
    { key: 'edition_date', title: 'Дата редакции', kind: 'date' },
    { key: 'page', title: 'Страница', kind: 'text', optional: true },
  ],
  REVIEWER_DECISION: [
    { key: 'decided_by', title: 'Кто решил', kind: 'text' },
    { key: 'decided_at', title: 'Дата решения', kind: 'date' },
    { key: 'reference', title: 'Протокол, письмо, задача', kind: 'text' },
    { key: 'basis', title: 'Основание решения', kind: 'long' },
  ],
  OWNER_DECISION: [
    { key: 'decided_by', title: 'Кто решил', kind: 'text' },
    { key: 'decided_at', title: 'Дата решения', kind: 'date' },
    { key: 'reference', title: 'Протокол, письмо, задача', kind: 'text' },
    { key: 'basis', title: 'Основание решения', kind: 'long' },
  ],
};

/** Типы правила, которые форма умеет оформить, из допустимых заявкой. */
export const offeredTypes = (need: CalcVkRuleNeedRead): CalcRuleType[] =>
  need.rule_types.filter((type) => SOURCE_KINDS[type].length > 0);

/** Заявки всех калькуляторов без повторов: общие решения (концевые участки) — одной строкой. */
export const uniqueNeeds = (
  calculators: readonly Pick<CalcVkCalculatorRead, 'rules'>[],
): CalcVkRuleNeedRead[] => {
  const found = new Map<string, CalcVkRuleNeedRead>();
  for (const calculator of calculators) {
    for (const rule of calculator.rules) {
      if (!found.has(rule.rule_key)) found.set(rule.rule_key, rule);
    }
  }
  return [...found.values()].sort((a, b) => Number(b.gate) - Number(a.gate));
};

export type NeedState =
  | { kind: 'not_implemented' }
  | { kind: 'none' }
  | { kind: 'draft'; version: number; approved: number | null }
  | { kind: 'approved'; version: number }
  | { kind: 'closed'; version: number };

/** Где заявка сейчас: по строке списка правил пространства. */
export const needState = (
  need: CalcVkRuleNeedRead,
  summary: CalcRuleSummaryRead | undefined,
): NeedState => {
  if (need.implementation_key === null) return { kind: 'not_implemented' };
  if (!summary) return { kind: 'none' };
  if (summary.latest_status === 'DRAFT') {
    return { kind: 'draft', version: summary.latest_version, approved: summary.approved_version };
  }
  if (summary.approved_version !== null)
    return { kind: 'approved', version: summary.approved_version };
  return { kind: 'closed', version: summary.latest_version };
};

export interface IDecisionInput {
  ruleType: CalcRuleType;
  parameters: Record<string, string>;
  sourceKind: SourceKind;
  source: Record<string, string>;
  limitations: string;
  impact: string;
  changeReason: string;
}

const DECIMAL = /^-?\d+(\.\d+)?$/;

const sourceOf = (kind: SourceKind, values: Readonly<Record<string, string>>): RuleSource => {
  const value = (key: string): string => values[key] ?? '';
  switch (kind) {
    case 'ENGINEERING_METHOD':
      return {
        kind,
        title: value('title'),
        author: value('author'),
        reference: value('reference'),
        summary: value('summary'),
      };
    case 'NORMATIVE_DOCUMENT':
      return {
        kind,
        document_title: value('document_title'),
        designation: value('designation'),
        edition: value('edition'),
        clause: value('clause'),
        edition_date: value('edition_date'),
        page: value('page') || null,
      };
    case 'REVIEWER_DECISION':
    case 'OWNER_DECISION':
      return {
        kind,
        decided_by: value('decided_by'),
        decided_at: value('decided_at'),
        reference: value('reference'),
        basis: value('basis'),
      };
  }
};

/** Десятичная запись: запятая как разделитель допускается, пробелы между разрядами — тоже. */
export const decimalText = (text: string): string | null => {
  const cleaned = text.replace(/[\s ]/g, '').replace(',', '.');
  return DECIMAL.test(cleaned) ? cleaned : null;
};

/** Тело запроса или текст ошибки — что именно не заполнено. */
export const buildDecision = (
  need: CalcVkRuleNeedRead,
  input: IDecisionInput,
  needsReason: boolean,
): CalcVkRuleVersionCreate | string => {
  const parameters: CalcVkRuleVersionCreate['parameters'] = [];
  for (const term of need.parameters) {
    const value = decimalText(input.parameters[term.name] ?? '');
    if (value === null) return `Параметр «${term.meaning}»: нужно число`;
    parameters.push({ name: term.name, value });
  }
  const fields = SOURCE_FIELDS[input.sourceKind];
  const source: Record<string, string> = {};
  for (const field of fields) {
    const value = (input.source[field.key] ?? '').trim();
    if (!value && !field.optional) return `Основание: заполните «${field.title}»`;
    if (value) source[field.key] = value;
  }
  if (input.ruleType === 'TENDER_ASSUMPTION' && !input.impact.trim()) {
    return 'У тендерного допущения нужно описать влияние на результат';
  }
  if (needsReason && input.changeReason.trim().length < 3) {
    return 'Укажите, почему нужна новая версия';
  }
  return {
    rule_type: input.ruleType,
    parameters,
    sources: [sourceOf(input.sourceKind, source)],
    limitations: input.limitations
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
    impact: input.impact.trim() || null,
    change_reason: needsReason ? input.changeReason.trim() : null,
  };
};

/** Значения параметров версии — для правки черновика или новой версии на её основе. */
export const parameterValues = (version: CalcRuleVersionRead | undefined): Record<string, string> =>
  Object.fromEntries(
    (version?.content.parameters ?? []).map((item) => [item.name, item.value.replace('.', ',')]),
  );

const SOURCE_KIND_SET: ReadonlySet<string> = new Set(Object.keys(SOURCE_FIELDS));

const isSourceKind = (kind: string | undefined): kind is SourceKind =>
  kind !== undefined && SOURCE_KIND_SET.has(kind);

/** Основание прежней версии — чтобы правка не начиналась с пустой формы. */
export const sourcePrefill = (
  version: CalcRuleVersionRead | undefined,
): { kind: SourceKind; values: Record<string, string> } | null => {
  for (const source of version?.content.sources ?? []) {
    if (isSourceKind(source.kind)) {
      const values: Record<string, string> = {};
      for (const [key, value] of Object.entries(source)) {
        if (key !== 'kind' && typeof value === 'string') values[key] = value;
      }
      return { kind: source.kind, values };
    }
  }
  return null;
};

type AnySource = NonNullable<CalcRuleVersionRead['content']['sources']>[number];

/** Основание одной строкой — для проверяющего. */
export const sourceLine = (source: AnySource): string => {
  switch (source.kind) {
    case 'NORMATIVE_DOCUMENT':
      return `${source.designation} «${source.document_title}», ${source.edition}, ${source.clause}, ред. ${source.edition_date}`;
    case 'ENGINEERING_METHOD':
      return `Методика «${source.title}», ${source.author}: ${source.reference}. ${source.summary}`;
    case 'OWNER_DECISION':
    case 'REVIEWER_DECISION':
      return `${source.kind === 'OWNER_DECISION' ? 'Решение владельца' : 'Решение проверяющего'}: ${source.decided_by}, ${source.decided_at}, ${source.reference}. ${source.basis}`;
    case 'MANUFACTURER_DOCUMENT':
      return `${source.manufacturer} ${source.product_line}: ${source.document_title}, ${source.document_version}, ${source.location}`;
    case 'LEGACY_CODE':
      return `Старый портал (происхождение, не основание): ${source.legacy_ids.join(', ')}`;
    default:
      return 'description' in source ? source.description : 'Иное основание';
  }
};
