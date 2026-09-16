import type { MepScenarioRead } from '@quantor/api-client';

import complete from './scenario-complete.json';
import hybrid from './scenario-hybrid.json';
import partial from './scenario-partial.json';
import refused from './scenario-refused.json';

/**
 * Ответы `GET /api/v1/mep/experiment/scenarios/{id}`, снятые с настоящего эндпоинта.
 * Совпадение с сервером проверяет `apps/api/tests/test_mep_experiment_api.py`.
 * JSON-импорт теряет литеральные типы, поэтому тип задаётся здесь один раз.
 */
const asScenario = (value: unknown): MepScenarioRead => value as MepScenarioRead;

export const SCENARIO_COMPLETE = asScenario(complete);
export const SCENARIO_PARTIAL = asScenario(partial);
export const SCENARIO_REFUSED = asScenario(refused);
export const SCENARIO_HYBRID = asScenario(hybrid);
