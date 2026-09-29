import type { CalcPassportRead } from '@quantor/api-client';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { VkUnresolved } from './VkIssues';

/**
 * Неопределённости паспорта: расхождение документа с правилом и предупреждения расчёта видны
 * инженеру — ни одно не превращается в число молча.
 */

type Body = Pick<CalcPassportRead['body'], 'unresolved' | 'conflicts' | 'warnings'>;

const body = (overrides: Partial<Body>): Body => ({
  unresolved: [],
  conflicts: [],
  warnings: [],
  ...overrides,
});

describe('неопределённости паспорта ВК', () => {
  it('пусто — только когда нет ни неопределённостей, ни расхождений, ни предупреждений', () => {
    render(<VkUnresolved body={body({})} />);
    expect(screen.getByText('Неопределённостей нет')).toBeInTheDocument();
  });

  it('расхождения и предупреждения показаны отдельно', () => {
    render(
      <VkUnresolved
        body={body({
          conflicts: [
            {
              fact_key: 'system.risers_count@building=1|discipline=VK|system_code=В1',
              message: 'В документе 4, правило даёт 5–6 — принят документ',
            },
          ],
          warnings: ['Решение инженера по узлу «risers» этим синтезатором не применяется'],
        })}
      />,
    );
    expect(screen.getByText('Расхождения источников')).toBeInTheDocument();
    expect(screen.getByText(/В документе 4, правило даёт 5–6/)).toBeInTheDocument();
    expect(screen.getByText('Предупреждения расчёта')).toBeInTheDocument();
    expect(screen.getByText(/не применяется/)).toBeInTheDocument();
    expect(screen.queryByText('Неопределённостей нет')).toBeNull();
  });
});
