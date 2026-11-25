import { describe, expect, it } from 'vitest';

import {
  bestCandidate,
  buildAttentionQueue,
  docItems,
  readSnoozed,
  scaleItem,
  writeSnoozed,
} from './attentionQueue';
import { candidate, question, questionsOut, scaleFailedSheet } from './fixtures';

const NOW = 1_000_000;

describe('очередь прямых вопросов', () => {
  it('лучший кандидат - с наибольшей оценкой, отклонённые не считаются', () => {
    const best = bestCandidate(
      question({
        candidates: [
          candidate({ id: 'a', score: 10 }),
          candidate({ id: 'b', score: 90, status: 'rejected' }),
          candidate({ id: 'c', score: 30 }),
        ],
      }),
    );

    expect(best?.id).toBe('c');
  });

  it('вопрос с подтверждённым ответом в очередь не попадает', () => {
    const answered = question({
      answers: [{ id: 'a-1' } as never],
      candidates: [candidate()],
    });

    expect(docItems(questionsOut([answered]))).toEqual([]);
  });

  it('вопрос без кандидатов задаётся только после завершённого поиска', () => {
    const empty = question();

    expect(docItems(questionsOut([empty], null))).toEqual([]);
    expect(docItems(questionsOut([empty], 'running'))).toEqual([]);
    expect(docItems(questionsOut([empty], 'succeeded'))).toHaveLength(1);
  });

  it('приоритет: масштаб CAD, затем с кандидатом по оценке, затем без кандидата', () => {
    const scale = scaleItem('p-1', 'r-1', 'АР.pdf', scaleFailedSheet(6));
    const docs = docItems(
      questionsOut([
        question({ code: 'slab_thickness' }),
        question({ code: 'clear_height', candidates: [candidate({ score: 10 })] }),
        question({ code: 'storeys', candidates: [candidate({ score: 70 })] }),
      ]),
    );

    const queue = buildAttentionQueue(scale ? [scale] : [], docs, {}, NOW);

    expect(queue.map((item) => item.id)).toEqual([
      'scale:r-1:6',
      'doc:storeys',
      'doc:clear_height',
      'doc:slab_thickness',
    ]);
  });

  it('вопрос о масштабе ведёт к калибровке листа и называет лист и документ', () => {
    const item = scaleItem('p-1', 'r-1', 'АР.pdf', scaleFailedSheet(6));

    expect(item?.text).toContain('Лист 7 (АР.pdf)');
    expect(item?.href).toContain('/projects/p-1/workspace');
    expect(item?.href).toContain('revision=r-1');
    expect(item?.href).toContain('page=7');
  });

  it('лист с калибровкой или без отказа масштаба вопроса не даёт', () => {
    expect(
      scaleItem('p-1', 'r-1', 'АР.pdf', { ...scaleFailedSheet(1), calibrated: true }),
    ).toBeNull();
    expect(scaleItem('p-1', 'r-1', 'АР.pdf', { ...scaleFailedSheet(1), convert: null })).toBeNull();
  });

  it('отложенный вопрос скрыт до истечения срока', () => {
    const docs = docItems(questionsOut([question({ candidates: [candidate()] })]));

    expect(buildAttentionQueue([], docs, { 'doc:clear_height': NOW + 1 }, NOW)).toEqual([]);
    expect(buildAttentionQueue([], docs, { 'doc:clear_height': NOW }, NOW)).toHaveLength(1);
  });

  it('отсрочка переживает перезагрузку, истёкшая отбрасывается', () => {
    writeSnoozed('p-1', { live: NOW + 10, dead: NOW - 10 });

    expect(readSnoozed('p-1', NOW)).toEqual({ live: NOW + 10 });
    expect(readSnoozed('p-2', NOW)).toEqual({});
  });
});
