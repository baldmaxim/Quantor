import { describe, expect, it } from 'vitest';

import { need, ruleVersion } from '@/components/calc/__fixtures__/rule-needs';

import {
  buildDecision,
  decimalText,
  needState,
  offeredTypes,
  sourcePrefill,
  uniqueNeeds,
  type IDecisionInput,
} from './rule-needs';

const INPUT: IDecisionInput = {
  ruleType: 'ENGINEERING',
  parameters: { per_riser_min: '2', per_riser_max: '3,5' },
  sourceKind: 'ENGINEERING_METHOD',
  source: { title: 'Методика', author: 'Инженер', reference: 'протокол гейта', summary: 'суть' },
  limitations: 'Только типовые этажи\n\n',
  impact: '',
  changeReason: '',
};

describe('решение инженера по заявке', () => {
  it('собирает тело: параметры заявки, основание, ограничения', () => {
    expect(buildDecision(need(), INPUT, false)).toEqual({
      rule_type: 'ENGINEERING',
      parameters: [
        { name: 'per_riser_min', value: '2' },
        { name: 'per_riser_max', value: '3.5' },
      ],
      sources: [
        {
          kind: 'ENGINEERING_METHOD',
          title: 'Методика',
          author: 'Инженер',
          reference: 'протокол гейта',
          summary: 'суть',
        },
      ],
      limitations: ['Только типовые этажи'],
      impact: null,
      change_reason: null,
    });
  });

  it('без числа, основания или причины новой версии — понятная ошибка', () => {
    expect(buildDecision(need(), { ...INPUT, parameters: { per_riser_min: '2' } }, false)).toMatch(
      /верхняя граница/,
    );
    expect(buildDecision(need(), { ...INPUT, source: { title: 'М' } }, false)).toMatch(
      /Автор или организация/,
    );
    expect(buildDecision(need(), INPUT, true)).toBe('Укажите, почему нужна новая версия');
  });

  it('тендерное допущение — с влиянием на результат', () => {
    const tender = { ...INPUT, ruleType: 'TENDER_ASSUMPTION' as const };
    expect(buildDecision(need(), tender, false)).toMatch(/влияние/);
  });

  it('число: запятая и пробелы между разрядами; не число — нет', () => {
    expect(decimalText('1 200,5')).toBe('1200.5');
    expect(decimalText('около 3')).toBeNull();
  });

  it('правило производителя форма не оформляет', () => {
    expect(offeredTypes(need({ rule_types: ['MANUFACTURER', 'ENGINEERING'] }))).toEqual([
      'ENGINEERING',
    ]);
  });

  it('общая заявка нескольких калькуляторов — одной строкой, нужные для гейта сверху', () => {
    const shared = need({ rule_key: 'vk.water.riser.end_segments' });
    const optional = need({ rule_key: 'vk.supports.spacing', gate: false });
    const calc = (rules: ReturnType<typeof need>[]) => ({ rules });
    const found = uniqueNeeds([calc([optional, shared]), calc([shared])]);
    expect(found.map((item) => item.rule_key)).toEqual([
      'vk.water.riser.end_segments',
      'vk.supports.spacing',
    ]);
  });

  it('состояние заявки — по строке реестра', () => {
    const summary = {
      rule_key: 'vk.b1.risers.count_range',
      discipline: 'VK' as const,
      title: '',
      rule_type: 'ENGINEERING' as const,
      systems: ['В1'],
      latest_version: 2,
      latest_status: 'DRAFT' as const,
      approved_version: 1,
      calculation_eligible: true,
      sources: [],
      notice: null,
    };
    expect(needState(need(), undefined)).toEqual({ kind: 'none' });
    expect(needState(need(), summary)).toEqual({ kind: 'draft', version: 2, approved: 1 });
    expect(needState(need(), { ...summary, latest_status: 'APPROVED' })).toEqual({
      kind: 'approved',
      version: 1,
    });
    expect(needState(need({ implementation_key: null }), summary)).toEqual({
      kind: 'not_implemented',
    });
  });

  it('правка начинается с основания прежней версии', () => {
    expect(sourcePrefill(ruleVersion())).toEqual({
      kind: 'ENGINEERING_METHOD',
      values: { title: 'Методика', author: 'Инженер', reference: 'протокол', summary: 'суть' },
    });
  });
});
