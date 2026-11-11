import { unzipSync } from 'fflate';
import { describe, expect, it } from 'vitest';

import { buildPackageZip, toLazyPackage } from './buildPackageZip';
import { planFolderUpload } from './packageFolder';

const makePackage = () => {
  const plan = planFolderUpload(
    [
      ['sub/АР-1.pdf', new Uint8Array([37, 80, 68, 70, 0, 1, 2, 3])],
      ['md/АР-1_results.md', '# заголовок\n'.repeat(100)],
      ['md/АР-1_results.html', '<p>текст</p>'],
      ['data/АР-1_blocks.json', '{"schema_version":1}'],
    ].map(([path, content]) => ({
      path: path as string,
      file: new File([content as BlobPart], (path as string).split('/').pop() ?? ''),
    })),
  );
  const pkg = plan.packages[0];
  if (!pkg) throw new Error('комплект не собран');
  return pkg;
};

describe('сборка ZIP пакета', () => {
  it('архив содержит 4 файла в корне с исходными именами и содержимым', async () => {
    const zip = await buildPackageZip(makePackage());

    expect(zip.name).toBe('АР-1.zip');
    expect(zip.type).toBe('application/zip');

    const files = unzipSync(new Uint8Array(await zip.arrayBuffer()));
    expect(Object.keys(files).sort()).toEqual(
      ['АР-1.pdf', 'АР-1_blocks.json', 'АР-1_results.html', 'АР-1_results.md'].sort(),
    );
    expect(Array.from(files['АР-1.pdf'] ?? [])).toEqual([37, 80, 68, 70, 0, 1, 2, 3]);
    expect(new TextDecoder().decode(files['АР-1_blocks.json'])).toBe('{"schema_version":1}');
  });

  it('отложенный пакет подписан и собирается только по build()', async () => {
    const lazy = toLazyPackage(makePackage());

    expect(lazy.name).toBe('АР-1.zip');
    expect(lazy.note).toBe('пакет из папки: 4 файла');
    expect((await lazy.build()).name).toBe('АР-1.zip');
  });
});
