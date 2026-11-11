import { describe, expect, it } from 'vitest';

import { planFolderUpload, type IFolderEntry } from './packageFolder';

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
