import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { fact, factType, inputFact } from './__fixtures__/calc';

import { InputFactsTable } from './InputFactsTable';

/**
 * Таблица фактов: идёт ли значение в расчёт — ответ сервера. Интерфейс его только называет.
 */

const TYPES = new Map([['floor.apartments_count', factType()]]);

describe('таблица фактов', () => {
  it('показывает значение, единицу, место, источник и уверенность', () => {
    render(<InputFactsTable items={[inputFact()]} factTypes={TYPES} />);
    expect(screen.getByText('Квартир на этаже')).toBeInTheDocument();
    expect(screen.getByText('кв.')).toBeInTheDocument();
    expect(screen.getByText('корп. 1 · эт. 2–24')).toBeInTheDocument();
    expect(screen.getByText('Квартирография · АР.pdf')).toBeInTheDocument();
    expect(screen.getByText('средняя')).toBeInTheDocument();
    expect(screen.getByText('да')).toBeInTheDocument();
  });

  it('факт из ВОР Заказчика помечен как неучаствующий в расчёте', () => {
    const vor = inputFact({
      usage: 'EXCLUDED_VOR',
      fact: fact({ source_class: 'CUSTOMER_VOR', calculation_eligible: false }),
      source_title: 'ВОР Заказчика · ВОР.pdf',
    });
    render(<InputFactsTable items={[vor]} factTypes={TYPES} />);
    expect(screen.getByText('нет — ВОР, только сверка')).toBeInTheDocument();
  });

  it('нерешённое расхождение видно в строке', () => {
    render(<InputFactsTable items={[inputFact({ usage: 'CONFLICT' })]} factTypes={TYPES} />);
    expect(screen.getByText('нет — расхождение')).toBeInTheDocument();
  });
});
