import { describe, expect, it } from 'vitest';

import {
  isMissingOnlyPdf,
  mergeFolderPlan,
  planFolderUpload,
  stemKey,
  type IFolderEntry,
} from './packageFolder';

const entry = (path: string): IFolderEntry => ({
  file: new File(['x'], path.split('/').pop() ?? path),
  path,
});

const full = (stem: string, dir = ''): IFolderEntry[] =>
  [`${stem}.pdf`, `${stem}_results.md`, `${stem}_results.html`, `${stem}_blocks.json`].map((name) =>
    entry(`${dir}${name}`),
  );

describe('разбор папки пакета', () => {
  it('полный комплект собирается в один пакет', () => {
    const plan = planFolderUpload(full('АР-1'));

    expect(plan.packages).toHaveLength(1);
    expect(plan.packages[0]?.stem).toBe('АР-1');
    expect(plan.packages[0]?.blocks.name).toBe('АР-1_blocks.json');
    expect(plan.plainFiles).toHaveLength(0);
    expect(plan.warnings).toHaveLength(0);
    expect(plan.skipped).toBe(0);
  });

  it('файлы комплекта в разных подпапках находятся', () => {
    const plan = planFolderUpload([
      entry('TENDER/attachments/АР-1.pdf'),
      entry('TENDER/markdown/АР-1_results.md'),
      entry('TENDER/markdown/АР-1_results.html'),
      entry('TENDER/data/АР-1_blocks.json'),
    ]);

    expect(plan.packages).toHaveLength(1);
    expect(plan.warnings).toHaveLength(0);
  });

  it('PDF без распознавания идёт как обычный файл', () => {
    const plan = planFolderUpload([entry('a/чертёж.pdf')]);

    expect(plan.packages).toHaveLength(0);
    expect(plan.plainFiles.map((file) => file.name)).toEqual(['чертёж.pdf']);
    expect(plan.warnings).toHaveLength(0);
  });

  it('распознавание без PDF — предупреждение, не загрузка', () => {
    const plan = planFolderUpload([
      entry('АР-1_results.md'),
      entry('АР-1_results.html'),
      entry('АР-1_blocks.json'),
    ]);

    expect(plan.packages).toHaveLength(0);
    expect(plan.plainFiles).toHaveLength(0);
    expect(plan.warnings).toEqual([{ stem: 'АР-1', missing: ['АР-1.pdf'] }]);
  });

  it('неполный комплект перечисляет, чего не хватает, и PDF не уходит отдельно', () => {
    const plan = planFolderUpload([entry('Х.pdf'), entry('Х_results.md')]);

    expect(plan.plainFiles).toHaveLength(0);
    expect(plan.warnings).toEqual([{ stem: 'Х', missing: ['Х_results.html', 'Х_blocks.json'] }]);
  });

  it('два комплекта дают два пакета', () => {
    const plan = planFolderUpload([...full('А', 'a/'), ...full('Б', 'b/')]);

    expect(plan.packages.map((pkg) => pkg.stem).sort()).toEqual(['А', 'Б']);
  });

  it('регистр расширений не важен', () => {
    const plan = planFolderUpload([
      entry('Z.PDF'),
      entry('Z_results.MD'),
      entry('Z_Results.Html'.replace('Results', 'results')),
      entry('Z_blocks.JSON'),
    ]);

    expect(plan.packages).toHaveLength(1);
    expect(plan.packages[0]?.stem).toBe('Z');
  });

  it('_source.json и прочее игнорируются и считаются', () => {
    const plan = planFolderUpload([
      ...full('А'),
      entry('А_source.json'),
      entry('.DS_Store'),
      entry('readme.txt'),
    ]);

    expect(plan.packages).toHaveLength(1);
    expect(plan.skipped).toBe(3);
  });

  it('BIM и ZIP из папки идут как обычные файлы', () => {
    const plan = planFolderUpload([entry('m/корпус.nwd'), entry('m/готовый.zip')]);

    expect(plan.plainFiles.map((file) => file.name).sort()).toEqual(['готовый.zip', 'корпус.nwd']);
  });
});

const recognition = (stem: string, dir = 'rec/'): IFolderEntry[] =>
  [`${stem}_results.md`, `${stem}_results.html`, `${stem}_blocks.json`, `${stem}_source.json`].map(
    (name) => entry(`${dir}${name}`),
  );

const NONE: ReadonlySet<string> = new Set();

describe('комплект из нескольких выборов', () => {
  it('папка распознавания без PDF ждёт; только PDF не хватает', () => {
    const first = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: recognition('АР-1'),
      existingStems: NONE,
      existingPdfStems: NONE,
    });

    expect(first.packages).toHaveLength(0);
    expect(first.pending).toHaveLength(3);
    expect(first.skipped).toBe(1);
    expect(first.warnings.map(isMissingOnlyPdf)).toEqual([true]);
  });

  it('PDF после папки достраивает комплект и не идёт обычным файлом', () => {
    const first = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: recognition('АР-1'),
      existingStems: NONE,
      existingPdfStems: NONE,
    });
    const second = mergeFolderPlan({
      pending: first.pending,
      loosePdfs: [],
      incoming: [entry('pdf/АР-1.pdf'), entry('pdf/Б.pdf')],
      existingStems: NONE,
      existingPdfStems: NONE,
    });

    expect(second.packages.map((pkg) => pkg.stem)).toEqual(['АР-1']);
    expect(second.plainFiles.map((file) => file.name)).toEqual(['Б.pdf']);
    expect(second.pending).toHaveLength(0);
    expect(second.warnings).toHaveLength(0);
    expect(second.skipped).toBe(0);
  });

  it('PDF, выбранный раньше папки, переезжает из обычных в пакет', () => {
    const loose = new File(['x'], 'АР-1.pdf');
    const other = new File(['x'], 'Б.pdf');
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [loose, other],
      incoming: recognition('АР-1'),
      existingStems: NONE,
      existingPdfStems: NONE,
    });

    expect(plan.packages.map((pkg) => pkg.stem)).toEqual(['АР-1']);
    expect(plan.consumed).toEqual([loose]);
    expect(plan.plainFiles).toHaveLength(0);
  });

  it('части распознавания из двух папок плюс PDF собираются в один пакет', () => {
    const first = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: [entry('a/Х_results.md')],
      existingStems: NONE,
      existingPdfStems: NONE,
    });
    const second = mergeFolderPlan({
      pending: first.pending,
      loosePdfs: [],
      incoming: [entry('b/Х_results.html'), entry('b/Х_blocks.json')],
      existingStems: NONE,
      existingPdfStems: NONE,
    });

    expect(second.warnings).toEqual([{ stem: 'Х', missing: ['Х.pdf'] }]);
    const third = mergeFolderPlan({
      pending: second.pending,
      loosePdfs: [],
      incoming: [entry('Х.pdf')],
      existingStems: NONE,
      existingPdfStems: NONE,
    });
    expect(third.packages).toHaveLength(1);
  });

  it('пакет уже в проекте: не предупреждение и не ожидание', () => {
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: recognition('АР-1'),
      existingStems: new Set(['ар-1']),
      existingPdfStems: NONE,
    });

    expect(plan.warnings).toHaveLength(0);
    expect(plan.pending).toHaveLength(0);
    expect(plan.alreadyInProject).toEqual(['АР-1']);
  });

  it('обычный PDF без распознавания рядом не трогается', () => {
    const loose = new File(['x'], 'Б.pdf');
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [loose],
      incoming: recognition('АР-1'),
      existingStems: NONE,
      existingPdfStems: NONE,
    });

    expect(plan.consumed).toHaveLength(0);
  });

  it('частичный комплект: не только PDF — старый текст', () => {
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: [entry('Х_results.md')],
      existingStems: NONE,
      existingPdfStems: NONE,
    });

    expect(plan.warnings.map(isMissingOnlyPdf)).toEqual([false]);
  });

  it('распознавание без PDF, а PDF уже в проекте: пакет без PDF, не ожидание', () => {
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: recognition('АР-1'),
      existingStems: NONE,
      existingPdfStems: new Set(['ар-1']),
    });

    expect(plan.packages).toHaveLength(1);
    expect(plan.packages[0]?.stem).toBe('АР-1');
    expect(plan.packages[0]?.pdf).toBeNull();
    expect(plan.attachToExisting).toEqual(['АР-1']);
    expect(plan.warnings).toHaveLength(0);
    expect(plan.pending).toHaveLength(0);
    expect(plan.alreadyInProject).toHaveLength(0);
  });

  it('PDF проекта с другим именем: комплект ждёт PDF, как раньше', () => {
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: recognition('АР-1'),
      existingStems: NONE,
      existingPdfStems: new Set(['другой']),
    });

    expect(plan.packages).toHaveLength(0);
    expect(plan.attachToExisting).toHaveLength(0);
    expect(plan.warnings.map(isMissingOnlyPdf)).toEqual([true]);
    expect(plan.pending).toHaveLength(3);
  });

  it('пакет уже в проекте важнее PDF проекта: «уже в проекте»', () => {
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: recognition('АР-1'),
      existingStems: new Set(['ар-1']),
      existingPdfStems: new Set(['ар-1']),
    });

    expect(plan.packages).toHaveLength(0);
    expect(plan.attachToExisting).toHaveLength(0);
    expect(plan.alreadyInProject).toEqual(['АР-1']);
  });

  it('не только PDF не хватает: PDF проекта комплект не достраивает', () => {
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: [entry('АР-1_results.md')],
      existingStems: NONE,
      existingPdfStems: new Set(['ар-1']),
    });

    expect(plan.packages).toHaveLength(0);
    expect(plan.warnings.map(isMissingOnlyPdf)).toEqual([false]);
  });
});

describe('сопоставление распознавания с PDF: пробелы и подчёркивания', () => {
  it('комплект с «_» вместо пробелов прикрепляется к PDF проекта', () => {
    const plan = mergeFolderPlan({
      pending: [],
      loosePdfs: [],
      incoming: recognition('МЛДГВ-КАМ_0925-П-КР2_(Часть_1)_ver3'),
      existingStems: NONE,
      existingPdfStems: new Set([stemKey('МЛДГВ-КАМ_0925-П-КР2 (Часть 1)_ver3')]),
    });

    expect(plan.packages.map((pkg) => pkg.stem)).toEqual(['МЛДГВ-КАМ_0925-П-КР2_(Часть_1)_ver3']);
    expect(plan.packages[0]?.pdf).toBeNull();
    expect(plan.attachToExisting).toEqual(['МЛДГВ-КАМ_0925-П-КР2_(Часть_1)_ver3']);
    expect(plan.warnings).toHaveLength(0);
    expect(plan.pending).toHaveLength(0);
  });

  it('stemKey: пробелы и подчёркивания — один символ, регистр не важен', () => {
    expect(stemKey('A  b_c')).toBe('a_b_c');
  });
});
