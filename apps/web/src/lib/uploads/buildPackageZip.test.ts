import { unzipSync } from 'fflate';
import { describe, expect, it } from 'vitest';

import { buildPackageZip, toLazyPackage } from './buildPackageZip';
import { planFolderUpload } from './packageFolder';
import { crc32, READ_CHUNK_BYTES } from './zipWriter';

const makePackage = (pdf: Uint8Array = new Uint8Array([37, 80, 68, 70, 0, 1, 2, 3])) => {
  const plan = planFolderUpload(
    [
      ['sub/АР-1.pdf', pdf],
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

  it('содержимое всех 4 файлов совпадает побайтно, имена с кириллицей сохраняются', async () => {
    const pkg = makePackage();
    const zip = await buildPackageZip(pkg);
    const files = unzipSync(new Uint8Array(await zip.arrayBuffer()));

    for (const file of [pkg.pdf, pkg.resultsMd, pkg.resultsHtml, pkg.blocks]) {
      const expected = new Uint8Array(await file.arrayBuffer());
      expect(files[file.name]).toEqual(expected);
    }
    expect(Object.keys(files).every((name) => name.startsWith('АР-1'))).toBe(true);
  });

  it('CRC32 строки "123456789" равен 0xCBF43926', () => {
    expect(crc32(new TextEncoder().encode('123456789'))).toBe(0xcbf43926);
  });

  it('PDF не кратного куску размера проходит потоковый CRC', async () => {
    const pdf = new Uint8Array(READ_CHUNK_BYTES + 3);
    for (let i = 0; i < pdf.length; i += 1) pdf[i] = (i * 31 + 7) & 0xff;
    const zip = await buildPackageZip(makePackage(pdf));

    const files = unzipSync(new Uint8Array(await zip.arrayBuffer()));
    const restored = files['АР-1.pdf'];
    // toEqual на 4 МБ неоправданно медленный — сравниваем через Buffer.
    expect(restored !== undefined && Buffer.from(restored).equals(Buffer.from(pdf))).toBe(true);
  });
});
