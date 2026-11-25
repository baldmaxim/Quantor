import { describe, expect, it } from 'vitest';

import { nextProjectStep, projectExtraLinks, projectSteps } from './project-steps';

const ALL = {
  'cad.export': true,
  'project.consistency': true,
  'model.import': true,
  'tender.exchange': true,
  'tender.versions': true,
};

describe('путь проекта', () => {
  it('все разделы включены: семь шагов по порядку, у каждого адрес и подсказка', () => {
    const steps = projectSteps('p1', ALL);
    expect(steps.map((step) => step.title)).toEqual([
      'Документы',
      'Листы комплекта',
      'CAD по листам',
      'Здание',
      'Модель здания',
      'База объекта',
      'Доступ',
    ]);
    expect(steps.map((step) => step.href)).toEqual([
      '/projects/p1',
      '/projects/p1/sheets',
      '/projects/p1',
      '/projects/p1/building3d',
      '/projects/p1/model',
      '/projects/p1/calcs?tab=base',
      '/projects/p1/calcs?tab=tokens',
    ]);
    expect(steps.every((step) => step.hint.length > 0)).toBe(true);
  });

  it('разделы под выключенными флагами не показываются', () => {
    expect(projectSteps('p1', {}).map((step) => step.key)).toEqual(['documents']);
    expect(projectSteps('p1', { 'cad.export': true }).map((step) => step.key)).toEqual([
      'documents',
      'cad',
      'building',
    ]);
  });

  it('следующий шаг - с другим адресом: после документов листы, после листов - CAD', () => {
    const steps = projectSteps('p1', ALL);
    expect(nextProjectStep(steps, 'documents')?.key).toBe('sheets');
    expect(nextProjectStep(steps, 'sheets')?.key).toBe('cad');
    expect(nextProjectStep(steps, 'building')?.key).toBe('model');
    expect(nextProjectStep(steps, 'model')?.key).toBe('base');
    expect(nextProjectStep(steps, 'base')?.key).toBe('access');
    expect(nextProjectStep(steps, 'access')).toBeNull();
  });

  it('без листов комплекта после документов - «Здание», а не CAD на той же странице', () => {
    const steps = projectSteps('p1', { 'cad.export': true });
    expect(nextProjectStep(steps, 'documents')?.key).toBe('building');
    // Шага нет на странице (флаг выключен) - следующего тоже нет.
    expect(nextProjectStep(steps, 'model')).toBeNull();
  });

  it('разделы вне пути - отдельными ссылками', () => {
    expect(projectExtraLinks('p1', ALL).map((link) => link.label)).toEqual([
      'Вопросы к документации',
      'Каркас здания',
      'Версии тендера',
      'Расчёты',
      'ВОР',
    ]);
    expect(projectExtraLinks('p1', { 'cad.export': true })).toEqual([
      { label: 'ВОР', href: '/projects/p1/vor' },
    ]);
    expect(projectExtraLinks('p1', {})).toEqual([]);
  });
});
