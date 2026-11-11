import { describe, expect, it } from 'vitest';

import { documentSection, groupDocuments, SECTION_TITLES } from './documentSections';

const doc = (
  id: string,
  name: string,
  kind: 'pdf' | 'recognized_package' | 'other' | 'ifc' = 'pdf',
) => ({
  id,
  display_name: name,
  document_kind: kind,
});

describe('раздел по шифру в имени', () => {
  it.each([
    ['МЛДГВ-КАМ0925-П-АР1.1_ver5.pdf', 'ar', 'АР1.1'],
    ['МЛДГВ-КАМ-0925-П-ИОС2.1_ver4.pdf', 'ios2', 'ИОС2.1'],
    ['МЛДГВ-КАМ-0925-П-ИОС2.2_ver4.pdf', 'ios2', 'ИОС2.2'],
    ['МЛД-ЖК-П-ИОС2.3.pdf', 'ios2', 'ИОС2.3'],
    ['МЛДГВ-КАМ-0925-П-ИОС3.1_ver5.pdf', 'ios3', 'ИОС3.1'],
    ['МЛД-ЖК-П-ИОС3.2_ver4.pdf', 'ios3', 'ИОС3.2'],
    ['МЛДГВ-КАМ-0925-П-ИОС4.1_ver5.pdf', 'ios4', 'ИОС4.1'],
    ['МЛДГВ-КАМ-0925-П-ИОС4.4_ver4.pdf', 'ios4', 'ИОС4.4'],
    ['Проект-П-ИОС1.pdf', 'ios1', 'ИОС1'],
    ['Проект-П-ИОС5.1.pdf', 'ios5', 'ИОС5.1'],
    ['Проект-П-ИОС6.pdf', 'ios6', 'ИОС6'],
    ['Проект-П-ИОС7.pdf', 'ios7', 'ИОС7'],
    ['Дом-РД-КР2.pdf', 'kr', 'КР2'],
    ['Дом-РД-КЖ1.3.pdf', 'kr', 'КЖ1.3'],
    ['Дом-РД-КМ.pdf', 'kr', 'КМ'],
    ['Дом-РД-ЭОМ1.pdf', 'ios1', 'ЭОМ1'],
    ['Дом-РД-ВК.pdf', 'ios2', 'ВК'],
    ['Дом-РД-В.pdf', 'ios2', 'В'],
    ['Дом-РД-К.pdf', 'ios3', 'К'],
    ['Дом-РД-ОВиК.pdf', 'ios4', 'ОВИК'],
    ['Дом-РД-СС.pdf', 'ios5', 'СС'],
    ['Дом-РД-ТХ.pdf', 'ios6', 'ТХ'],
    ['Дом-РД-ГС.pdf', 'ios7', 'ГС'],
    ['Дом-П-ПЗУ.pdf', 'pzu', 'ПЗУ'],
    ['Дом-П-ГП.pdf', 'pzu', 'ГП'],
    ['Дом-П-ПОС.pdf', 'pos', 'ПОС'],
    ['Дом-П-МПБ.pdf', 'pb', 'МПБ'],
    ['Дом-П-ООС.pdf', 'oos', 'ООС'],
    ['Дом-П-ОДИ.pdf', 'odi', 'ОДИ'],
    ['Дом-П-ЭЭ.pdf', 'ee', 'ЭЭ'],
    ['Дом-П-СМ.pdf', 'sm', 'СМ'],
    ['Дом-П-ЭЭФ.pdf', 'ee', 'ЭЭФ'],
    ['МЛДГВ-КАМ-0925-П-ПЗ_ver27.pdf', 'general', 'ПЗ'],
    ['МЛДГВ-КАМ-0925-П-СП_ver10.pdf', 'general', 'СП'],
    ['МЛДГВ-КАМ0925-П-ИРД_ver2.pdf', 'general', 'ИРД'],
    ['МЛДГВ-КАМ-0925-П-ПЗ_ver27.zip', 'general', 'ПЗ'],
    ['МЛДГВ-КАМ-0925-П-СП_ver10.zip', 'general', 'СП'],
    ['МЛДГВ-КАМ0925-П-ИРД_ver2.zip', 'general', 'ИРД'],
    ['100-25-ГК-ИГИ-2.1.pdf', 'surveys', 'ИГИ'],
    ['100-25-ГК-ИГИ-2.1_results.pdf', 'surveys', 'ИГИ'],
    ['ГСТ-22-26-ИГДИ.pdf', 'surveys', 'ИГДИ'],
    ['ГСТ-22-26-ИЭИ.pdf', 'surveys', 'ИЭИ'],
    ['ГСТ-22-26-ИГМИ.pdf', 'surveys', 'ИГМИ'],
  ])('%s → %s', (name, section, code) => {
    expect(documentSection(name, 'pdf')).toEqual({ section, code });
  });

  it('регистр и латинские двойники не мешают', () => {
    expect(documentSection('дом-п-ар1.1.pdf', 'pdf').section).toBe('ar');
    expect(documentSection('Dom-P-AP1.1.pdf', 'pdf').section).toBe('ar');
    expect(documentSection('дом-п-иос4.2.pdf', 'pdf').section).toBe('ios4');
  });

  it('«СП» и «ПЗ» только отдельным токеном: «Спецификация» — не общая часть', () => {
    expect(documentSection('Спецификация.pdf', 'pdf').section).toBe('other');
    expect(documentSection('Спец-ПЗУ.pdf', 'pdf').section).toBe('pzu');
  });

  it('общая часть и изыскания идут первыми, в этом порядке', () => {
    const groups = groupDocuments([
      doc('1', 'Дом-П-АР1.pdf'),
      doc('2', 'ГСТ-22-26-ИГДИ.pdf'),
      doc('3', 'МЛДГВ-КАМ-0925-П-ПЗ_ver27.pdf'),
    ]);
    expect(groups.map((group) => group.id)).toEqual(['general', 'surveys', 'ar']);
    expect(groups[0]?.title).toBe('Общая часть: ПЗ, состав проекта, ИРД');
  });

  it('ИОС2.3 и ИОС3.2 не путаются', () => {
    expect(documentSection('X-П-ИОС2.3.pdf', 'pdf').section).toBe('ios2');
    expect(documentSection('X-П-ИОС3.2.pdf', 'pdf').section).toBe('ios3');
  });

  it('шифр без границ слова не считается: «МЛДГВ», «КАМ0925» — не раздел', () => {
    expect(documentSection('МЛДГВ-КАМ0925.pdf', 'pdf').section).toBe('other');
    expect(documentSection('ПАРК.pdf', 'pdf').section).toBe('other');
  });

  it('неизвестное имя — «Прочее»', () => {
    expect(documentSection('Письмо заказчика.pdf', 'pdf')).toEqual({
      section: 'other',
      code: null,
    });
  });

  it('ВОР, смета и таблицы — «Ведомости и таблицы»', () => {
    expect(documentSection('ВОР ИОС2.xlsx', 'other').section).toBe('tables');
    expect(documentSection('Смета корпус 9.pdf', 'pdf').section).toBe('tables');
    expect(documentSection('данные.xlsx', 'other').section).toBe('tables');
  });

  it('BIM — по виду документа и по расширению', () => {
    expect(documentSection('Модель-АР.rvt', 'other').section).toBe('bim');
    expect(documentSection('Модель', 'ifc').section).toBe('bim');
    expect(documentSection('сводная.nwd', 'other').section).toBe('bim');
  });
});

describe('группировка документов', () => {
  it('порядок групп и счётчики', () => {
    const groups = groupDocuments([
      doc('1', 'Письмо.pdf'),
      doc('2', 'М-П-ИОС4.1.pdf'),
      doc('3', 'М-П-АР1.1.pdf'),
      doc('4', 'М-П-ИОС2.1.pdf'),
      doc('5', 'М-П-ИОС2.2.pdf'),
      doc('6', 'Модель.ifc', 'ifc'),
    ]);

    expect(groups.map((group) => group.id)).toEqual(['ar', 'ios2', 'ios4', 'bim', 'other']);
    expect(groups[1]?.title).toBe(SECTION_TITLES.ios2);
    expect(groups[1]?.entries.map((entry) => entry.document.id)).toEqual(['4', '5']);
  });

  it('ZIP привязан к PDF того же имени и не получает своей строки', () => {
    const groups = groupDocuments([
      doc('pdf', 'МЛДГВ-КАМ0925-П-АР1.1_ver5.pdf'),
      doc('zip', 'МЛДГВ-КАМ0925-П-АР1.1_ver5.zip', 'recognized_package'),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.id).toBe('ar');
    expect(groups[0]?.entries).toHaveLength(1);
    expect(groups[0]?.entries[0]?.packages.map((item) => item.id)).toEqual(['zip']);
  });

  it('ZIP без PDF уходит в «Пакеты распознавания» в конце', () => {
    const groups = groupDocuments([
      doc('zip', 'М-П-ИОС2.1_ver4.zip', 'recognized_package'),
      doc('pdf', 'М-П-АР1.1.pdf'),
      doc('zip2', 'М-П-АР1.1_ver9.zip', 'recognized_package'),
    ]);

    expect(groups.map((group) => group.id)).toEqual(['ar', 'packages']);
    expect(groups[1]?.entries.map((entry) => entry.document.id)).toEqual(['zip', 'zip2']);
    expect(groups[0]?.entries[0]?.packages).toEqual([]);
  });
});
