import type { ModelVersionRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { modelAccess } from './model-access';
import {
  categoryLabel,
  elementTitle,
  formatElevation,
  parseElements,
  propertyRows,
  type IModelElement,
} from './model-elements';
import { pickVersion } from './model-versions';

const wall: IModelElement = {
  id: 'w1',
  category: 'wall',
  ifc_class: 'IfcWallStandardCase',
  name: 'Стена_200',
  type: 'Монолит 200',
  discipline: 'ARCH',
  props: { 'Pset.Fire': 'EI60', Несущая: true, Запас: null, Толщина: 200 },
};

const version = (id: string, status: string, number: number): ModelVersionRead =>
  ({ id, status, number }) as ModelVersionRead;

describe('элементы этажа', () => {
  it('JSON Lines: битые и не той формы строки пропускаются', () => {
    const text = [
      JSON.stringify(wall),
      '{broken',
      '',
      JSON.stringify({ id: 'x' }),
      JSON.stringify({ id: 'w2', category: 'door', discipline: 'ARCH' }),
    ].join('\n');
    const parsed = parseElements(text);
    expect([...parsed.keys()]).toEqual(['w1', 'w2']);
    expect(parsed.get('w1')?.name).toBe('Стена_200');
  });

  it('заголовок: имя, иначе тип, иначе категория по-русски', () => {
    expect(elementTitle(wall)).toBe('Стена_200');
    expect(elementTitle({ ...wall, name: ' ' })).toBe('Монолит 200');
    expect(elementTitle({ id: 'd', category: 'door', discipline: 'ARCH' })).toBe('Дверь');
    expect(categoryLabel('unknown_kind')).toBe('unknown_kind');
  });

  it('строки плашки: общие поля, затем свойства с русскими значениями', () => {
    expect(propertyRows(wall).map((row) => `${row.label}: ${row.value}`)).toEqual([
      'Категория: Стена',
      'Дисциплина: ARCH',
      'Тип: Монолит 200',
      'Класс IFC: IfcWallStandardCase',
      'Pset.Fire: EI60',
      'Несущая: да',
      'Запас: —',
      'Толщина: 200',
    ]);
  });
});

describe('этажи и версии', () => {
  it('отметка со знаком и запятой', () => {
    expect(formatElevation(10540)).toBe('+10,540');
    expect(formatElevation(-5940)).toBe('−5,940');
    expect(formatElevation(0)).toBe('+0,000');
    expect(formatElevation(-0.2)).toBe('+0,000');
  });

  it('открывается утверждённая версия, иначе новейшая законченная', () => {
    const items = [
      version('c', 'candidate', 3),
      version('u', 'uploading', 4),
      version('a', 'approved', 2),
    ];
    expect(pickVersion(items)).toBe('a');
    expect(pickVersion([version('u', 'uploading', 2), version('c', 'candidate', 1)])).toBe('c');
    expect(pickVersion([version('u', 'uploading', 1)])).toBeNull();
    expect(pickVersion([])).toBeNull();
  });

  it('доступ по флагу пространства', () => {
    expect(modelAccess(false, {})).toBe('pending');
    expect(modelAccess(true, { 'model.import': true })).toBe('open');
    expect(modelAccess(true, {})).toBe('hidden');
  });
});

describe('задание «Модель из IFC»', () => {
  it('подписи состояний и признак работы задания', async () => {
    const { importActive, importErrorText, importView } = await import('./model-versions');
    expect(importView('running')).toEqual({ label: 'строится', tone: 'accent' });
    expect(importView('failed').tone).toBe('danger');
    expect(importView('новое').label).toBe('новое');
    expect(importActive('queued')).toBe(true);
    expect(importActive('running')).toBe(true);
    expect(importActive('succeeded')).toBe(false);
    expect(importActive(null)).toBe(false);
    expect(importErrorText('MODEL_IFC_NOT_FOUND')).toContain('нет загруженных IFC');
    expect(importErrorText(null)).toContain('Не удалось');
  });
});
