import { describe, expect, it } from 'vitest';

import {
  draftOf,
  isEmptyPatch,
  patchOfDraft,
  propsOfDraft,
  samePropsDraft,
  type IPropsDraft,
} from './construction-props';
import { showBlockSize, showBrickLayout, constructionTitle } from './construction-labels';
import { construction } from './constructions-fixtures';

const blank = draftOf({});

const withNumber = (draft: IPropsDraft, key: keyof IPropsDraft['numbers'], value: string) => ({
  ...draft,
  numbers: { ...draft.numbers, [key]: value },
});

describe('черновик параметров', () => {
  it('пустая форма - только признак надпроёмных частей', () => {
    expect(propsOfDraft(blank)).toEqual({ props: { count_openings: true }, error: null });
  });

  it('в параметры входят заполненные поля, числа - целыми', () => {
    const draft = {
      ...withNumber(withNumber(blank, 'joint_mm', '3'), 'block_length_mm', '600'),
      material: 'aerated_concrete',
      text: { ...blank.text, density_grade: ' D500 ' },
    };
    expect(propsOfDraft(draft).props).toEqual({
      material: 'aerated_concrete',
      density_grade: 'D500',
      joint_mm: 3,
      block_length_mm: 600,
      count_openings: true,
    });
  });

  it('вне диапазона - ошибка с понятным текстом, поле не попадает в параметры', () => {
    const result = propsOfDraft(withNumber(blank, 'joint_mm', '99'));
    expect(result.error).toBe('Шов, мм: целое число от 1 до 30.');
    expect(result.props).not.toHaveProperty('joint_mm');
    expect(propsOfDraft(withNumber(blank, 'sound_rw_db', '4,5')).error).toContain('Rw');
  });

  it('draftOf возвращает то, что сохранено', () => {
    const draft = draftOf({ material: 'brick_solid', joint_mm: 10, note: 'х', count_openings: false });
    expect(draft.material).toBe('brick_solid');
    expect(draft.numbers.joint_mm).toBe('10');
    expect(draft.count_openings).toBe(false);
    expect(samePropsDraft(draft, draftOf({ material: 'brick_solid', joint_mm: 10, note: 'х', count_openings: false }))).toBe(true);
    expect(samePropsDraft(draft, blank)).toBe(false);
  });
});

describe('патч «применить ко всем»', () => {
  it('пустая форма - пустой патч', () => {
    expect(isEmptyPatch(patchOfDraft(blank, blank).props)).toBe(true);
  });

  it('только заполненные поля; признак надпроёмных частей - когда он изменён', () => {
    const draft = { ...blank, purpose: 'interior', count_openings: false };
    expect(patchOfDraft(draft, blank).props).toEqual({ purpose: 'interior', count_openings: false });
    expect(patchOfDraft({ ...blank, purpose: 'mop' }, blank).props).toEqual({ purpose: 'mop' });
  });
});

describe('подписи и видимость полей', () => {
  it('кирпич - кладка в кирпичах, блоки - размер блока, у монолита ни того, ни другого', () => {
    expect(showBrickLayout('masonry', 'brick_solid')).toBe(true);
    expect(showBlockSize('masonry', 'brick_solid')).toBe(false);
    expect(showBlockSize('masonry', 'aerated_concrete')).toBe(true);
    expect(showBrickLayout('masonry', 'aerated_concrete')).toBe(false);
    expect(showBlockSize('masonry', null)).toBe(true);
    expect(showBrickLayout('monolith_wall', null)).toBe(false);
    expect(showBlockSize('monolith_column', null)).toBe(false);
  });

  it('заголовок: вид и толщина, без толщины - «проверить»', () => {
    expect(constructionTitle(construction({ id: 'a' }))).toBe('Кладка, 120 мм');
    expect(
      constructionTitle(
        construction({
          id: 'b',
          kind: 'monolith_pylon',
          thickness_nominal_mm: null,
          computed: { ...construction({ id: 'x' }).computed, thickness_mm: null },
        }),
      ),
    ).toBe('Монолит — пилон, толщина не определена — проверить');
  });
});
