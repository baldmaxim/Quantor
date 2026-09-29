import type { CalcEvidenceRead } from '@quantor/api-client';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

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

  it('основание раскрывается со ссылкой на лист и блок документа', async () => {
    const table: CalcEvidenceRead = {
      id: 'e-1',
      kind: 'REGION_TABLE',
      created_at: '2026-09-28T10:00:00Z',
      document_revision_id: 'rev-1',
      page_index: 4,
      region_id: 'reg-7',
      region_sha256: null,
      region_locator: { kind: 'TABLE', table_index: 0, rows: [2, 3], column: null },
      sheet_id: null,
      bbox: null,
      locator: null,
      excerpt: 'Квартира № 12',
      basis: null,
      alternatives: [],
      author_id: null,
    };
    const item = inputFact({ fact: fact({ evidence: [table] }) });
    render(<InputFactsTable projectId="p-1" items={[item]} factTypes={TYPES} />);
    await userEvent.click(screen.getByRole('button', { name: 'Основание (1)' }));
    expect(
      screen.getByText('Таблица документа · лист 5 · таблица 1, строки 3, 4'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть в документе' })).toHaveAttribute(
      'href',
      '/projects/p-1/workspace?revision=rev-1&page=5&region=reg-7',
    );
  });

  it('своё ручное значение автор отзывает, но не проверяет', () => {
    const own = inputFact({
      fact: fact({ source_class: 'MANUAL', method: 'MANUAL', created_by: 'u-1' }),
    });
    render(
      <InputFactsTable
        items={[own]}
        factTypes={TYPES}
        canVerify
        canEdit
        currentUserId="u-1"
        onAction={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Отозвать' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Подтвердить' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Отклонить' })).toBeNull();
  });

  it('значение документа проверяет и тот, кто запускал сбор', async () => {
    const onAction = vi.fn();
    const collected = inputFact({ fact: fact({ inspection_id: 'i-1', created_by: 'u-1' }) });
    render(
      <InputFactsTable
        items={[collected]}
        factTypes={TYPES}
        canVerify
        canEdit
        currentUserId="u-1"
        onAction={onAction}
      />,
    );
    // Утверждение адаптера вручную не отзывается.
    expect(screen.queryByRole('button', { name: 'Отозвать' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить' }));
    expect(onAction).toHaveBeenCalledWith('confirm', collected.fact);
  });

  it('из строки расхождения открываются варианты', async () => {
    const onConflict = vi.fn();
    const item = inputFact({ usage: 'CONFLICT' });
    render(<InputFactsTable items={[item]} factTypes={TYPES} onConflict={onConflict} />);
    await userEvent.click(screen.getByRole('button', { name: 'Расхождение' }));
    expect(onConflict).toHaveBeenCalledWith(item.fact);
  });
});
