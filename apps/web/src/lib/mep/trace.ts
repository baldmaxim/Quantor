import type {
  BoqLine,
  Derivation,
  EvidenceElement,
  GenerationProvenance,
  InferenceStep,
  MepContractIssueRead,
  MepScenarioRead,
  NetworkNode,
  NetworkSegment,
  QuantityBlocker,
  SubjectRef,
  UnresolvedDecision,
} from '@quantor/api-client';

/**
 * Трассировка MEP-эксперимента: только связи, которые есть в контрактах.
 *
 * Прямые связи — поля контрактов: `BoqLine.source_ids`, `Derivation.evidence_ids` и `step_ids`,
 * `InferenceStep.evidence_ids`, `UnresolvedDecision.subject_ids`. Обратные — их обращение, ничего
 * сверх. Связи, которой нет в контракте, здесь нет: её не придумывает интерфейс.
 */

/** Происхождение сгенерированного элемента. Значения «наблюдено на П» у сети нет намеренно. */
export type NetworkOrigin = 'evidence' | 'rule' | 'prior' | 'human' | 'unresolved';

export const ORIGIN_BY_PROVENANCE: Readonly<Record<GenerationProvenance, NetworkOrigin>> = {
  evidence_observed: 'evidence',
  deterministic_rule: 'rule',
  rd_prior_inferred: 'prior',
  retrieved_pattern: 'prior',
  human_confirmed: 'human',
  unresolved: 'unresolved',
};

export const ORIGIN_LABEL: Readonly<Record<NetworkOrigin, string>> = {
  evidence: 'сгенерировано по evidence П',
  rule: 'сгенерировано правилом',
  prior: 'сгенерировано по опыту РД',
  human: 'подтверждено человеком',
  unresolved: 'не определено',
};

export const originOf = (derivation: Derivation): NetworkOrigin =>
  ORIGIN_BY_PROVENANCE[derivation.provenance];

export type NetworkItem =
  | { readonly kind: 'node'; readonly item: NetworkNode }
  | { readonly kind: 'segment'; readonly item: NetworkSegment };

export interface IMepTrace {
  readonly evidence: ReadonlyMap<string, EvidenceElement>;
  readonly network: ReadonlyMap<string, NetworkItem>;
  readonly steps: ReadonlyMap<string, InferenceStep>;
  readonly lines: ReadonlyMap<string, BoqLine>;
  /** Элемент сети → строки ВОР, где он источник (`BoqLine.sources[].subject`). */
  readonly linesByNetwork: ReadonlyMap<string, readonly string[]>;
  /** Элемент сети → строки ВОР, где он участник производной величины (`participants`). */
  readonly linesByParticipant: ReadonlyMap<string, readonly string[]>;
  /** Evidence → элементы сети, чья `Derivation` (или параметр) ссылается на него напрямую. */
  readonly networkByEvidence: ReadonlyMap<string, readonly string[]>;
  /** Шаг → элементы сети, чья `Derivation` (или параметр) ссылается на шаг. */
  readonly networkByStep: ReadonlyMap<string, readonly string[]>;
  /** Evidence → шаги, которые указали его входом. */
  readonly stepsByEvidence: ReadonlyMap<string, readonly string[]>;
}

const push = (map: Map<string, string[]>, key: string, value: string): void => {
  const list = map.get(key) ?? [];
  if (!list.includes(value)) {
    list.push(value);
  }
  map.set(key, list);
};

const derivationsOf = (item: NetworkItem): readonly Derivation[] => [
  item.item.derivation,
  ...(item.item.parameters ?? []).map((parameter) => parameter.derivation),
  ...(item.kind === 'node'
    ? (item.item.ports ?? []).flatMap((port) => (port.parameters ?? []).map((p) => p.derivation))
    : []),
];

export const buildTrace = (scenario: MepScenarioRead): IMepTrace => {
  const network = new Map<string, NetworkItem>();
  for (const node of scenario.network.nodes) {
    network.set(node.id, { kind: 'node', item: node });
  }
  for (const segment of scenario.network.segments ?? []) {
    network.set(segment.id, { kind: 'segment', item: segment });
  }

  const linesByNetwork = new Map<string, string[]>();
  const linesByParticipant = new Map<string, string[]>();
  for (const line of scenario.boq.lines) {
    for (const source of line.sources ?? []) {
      push(linesByNetwork, source.subject.id, line.line_id);
      for (const participant of source.participants ?? []) {
        if (participant.subject.id !== source.subject.id) {
          push(linesByParticipant, participant.subject.id, line.line_id);
        }
      }
    }
  }

  const networkByEvidence = new Map<string, string[]>();
  const networkByStep = new Map<string, string[]>();
  for (const [id, item] of network) {
    for (const derivation of derivationsOf(item)) {
      for (const evidenceId of derivation.evidence_ids ?? []) {
        push(networkByEvidence, evidenceId, id);
      }
      for (const stepId of derivation.step_ids ?? []) {
        push(networkByStep, stepId, id);
      }
    }
  }

  const stepsByEvidence = new Map<string, string[]>();
  for (const step of scenario.network.inference_steps ?? []) {
    for (const evidenceId of step.evidence_ids ?? []) {
      push(stepsByEvidence, evidenceId, step.id);
    }
  }

  return {
    evidence: new Map(scenario.evidence.elements.map((element) => [element.id, element])),
    network,
    steps: new Map((scenario.network.inference_steps ?? []).map((step) => [step.id, step])),
    lines: new Map(scenario.boq.lines.map((line) => [line.line_id, line])),
    linesByNetwork,
    linesByParticipant,
    networkByEvidence,
    networkByStep,
    stepsByEvidence,
  };
};

export const decisionsFor = (
  scenario: MepScenarioRead,
  id: string,
): readonly UnresolvedDecision[] =>
  (scenario.network.unresolved ?? []).filter((decision) =>
    (decision.subject_ids ?? []).includes(id),
  );

export const blockersFor = (scenario: MepScenarioRead, id: string): readonly QuantityBlocker[] =>
  (scenario.boq.blockers ?? []).filter((blocker) => (blocker.subject_ids ?? []).includes(id));

export const issuesFor = (
  issues: readonly MepContractIssueRead[],
  id: string,
): readonly MepContractIssueRead[] => issues.filter((issue) => issue.subject_id === id);

/** Подпись класса из профиля; неизвестный или неопределённый класс не маскируется. */
export const classLabel = (scenario: MepScenarioRead, key: string | null): string => {
  if (key === null) {
    return 'класс не определён';
  }
  return scenario.profile.classes.find((item) => item.key === key)?.label ?? key;
};

/** Куда ведёт типизированная ссылка. Виды без панели на странице переходов не получают. */
export const selectionFor = (ref: SubjectRef): MepSelection | null => {
  switch (ref.kind) {
    case 'node':
    case 'segment':
      return { kind: 'network', id: ref.id };
    case 'evidence_element':
      return { kind: 'evidence', id: ref.id };
    default:
      return null;
  }
};

/** Evidence, исправленный или подтверждённый человеком: по истории проверки, а не по догадке. */
export const reviewOf = (element: EvidenceElement): 'corrected' | 'confirmed' | 'added' | null => {
  const actions = (element.review_history ?? []).map((event) => event.action);
  if (actions.includes('add_missing')) return 'added';
  if (actions.some((action) => action.startsWith('correct_'))) return 'corrected';
  return actions.length > 0 ? 'confirmed' : null;
};

export type MepSelection =
  | { readonly kind: 'evidence'; readonly id: string }
  | { readonly kind: 'network'; readonly id: string }
  | { readonly kind: 'line'; readonly id: string };
