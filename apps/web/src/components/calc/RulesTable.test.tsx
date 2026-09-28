import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { legacyRule, ruleSummary } from './__fixtures__/rules';

import { LegacyRulesTable } from './LegacyRulesTable';
import { RulesTable } from './RulesTable';

/**
 * Экран правил: «разрешено в расчёте» — ответ сервера; тендерное допущение подписано;
 * каждое правило старого портала — не проверено и в расчёте не используется.
 */

describe('правила Quantor', () => {
  it('черновик не разрешён в расчёте', () => {
    render(<RulesTable items={[ruleSummary()]} />);
    expect(screen.getByText('Тестовая длина стояка')).toBeInTheDocument();
    expect(screen.getByText('черновик')).toBeInTheDocument();
    expect(screen.getByText('Геометрия')).toBeInTheDocument();
    expect(screen.getByText('нет')).toBeInTheDocument();
  });

  it('утверждённая версия и новая версия-черновик видны вместе', () => {
    const rule = ruleSummary({
      latest_version: 2,
      latest_status: 'DRAFT',
      approved_version: 1,
      calculation_eligible: true,
    });
    render(<RulesTable items={[rule]} />);
    expect(screen.getByText('v2 · утв. v1')).toBeInTheDocument();
    expect(screen.getByText('да')).toBeInTheDocument();
  });

  it('тендерное допущение подписано как не норматив', () => {
    const notice = 'Это не норматив и не факт документации. Это тендерное допущение.';
    render(<RulesTable items={[ruleSummary({ rule_type: 'TENDER_ASSUMPTION', notice })]} />);
    expect(screen.getByText('Тендерное допущение')).toBeInTheDocument();
    expect(screen.getByText(notice)).toBeInTheDocument();
  });
});

describe('карантин старого портала', () => {
  it('показывает класс, опасности, действие и статус', () => {
    render(<LegacyRulesTable items={[legacyRule()]} />);
    expect(screen.getByText('LEG-VK-001')).toBeInTheDocument();
    expect(screen.getByText('происхождение неизвестно')).toBeInTheDocument();
    expect(screen.getByText('скрытое умолчание')).toBeInTheDocument();
    expect(screen.getByText('сделать входом')).toBeInTheDocument();
    expect(screen.getByText('НЕ ПРОВЕРЕНО')).toBeInTheDocument();
    expect(screen.getByText('В РАСЧЁТЕ НЕ ИСПОЛЬЗУЕТСЯ')).toBeInTheDocument();
  });
});
