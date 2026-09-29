import type { DocumentKind } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { activeGroup, countByGroup, documentGroup, presentGroups } from './document-groups';

/**
 * Группы документов карточки проекта.
 *
 * Главный случай — распознанный пакет: после импорта рядом с архивом появляется PDF из него,
 * и список без переключателя выглядит как набор дублей.
 */

const docs = (...kinds: DocumentKind[]) => kinds.map((kind) => ({ document_kind: kind }));

describe('documentGroup', () => {
  it('раскладывает виды документов по группам', () => {
    expect(documentGroup('pdf')).toBe('pdf');
    expect(documentGroup('recognized_package')).toBe('zip');
    expect(documentGroup('revit')).toBe('bim');
    expect(documentGroup('navisworks')).toBe('bim');
    expect(documentGroup('ifc')).toBe('bim');
  });

  it('прочий вид не теряется, а попадает в последнюю группу', () => {
    expect(documentGroup('other')).toBe('bim');
  });
});

describe('countByGroup и presentGroups', () => {
  it('считает документы и оставляет только непустые группы по порядку', () => {
    const counts = countByGroup(docs('recognized_package', 'pdf', 'recognized_package', 'pdf'));

    expect(counts).toEqual({ pdf: 2, zip: 2, bim: 0 });
    expect(presentGroups(counts)).toEqual(['pdf', 'zip']);
  });

  it('пустой проект не даёт ни одной группы', () => {
    expect(presentGroups(countByGroup([]))).toEqual([]);
  });
});

describe('activeGroup', () => {
  it('по умолчанию показывает PDF, а не архивы', () => {
    expect(activeGroup(null, ['pdf', 'zip'])).toBe('pdf');
  });

  it('пока пакет импортируется и PDF нет, показывает архив', () => {
    expect(activeGroup(null, ['zip'])).toBe('zip');
  });

  it('выбор пользователя сохраняется', () => {
    expect(activeGroup('zip', ['pdf', 'zip'])).toBe('zip');
  });

  it('выбор пустой группы уступает первой непустой', () => {
    expect(activeGroup('bim', ['pdf', 'zip'])).toBe('pdf');
  });

  it('без документов группы нет', () => {
    expect(activeGroup(null, [])).toBeNull();
  });
});
