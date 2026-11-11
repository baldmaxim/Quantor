import { AsyncZipDeflate, Zip, ZipPassThrough } from 'fflate';

import type { IFolderPackage } from '@/lib/uploads/packageFolder';

/**
 * Сборка ZIP пакета legacy-v1 в браузере.
 *
 * Файлы лежат в корне архива под исходными именами. PDF уже сжат — кладётся без сжатия
 * (ZipPassThrough), тексты сжимаются в воркере fflate, чтобы не вешать страницу.
 * Файлы читаются кусками, а не целиком.
 */

const READ_CHUNK_BYTES = 4 * 1024 * 1024;

export const PACKAGE_FILE_COUNT = 4;

/** Отложенный пакет: ZIP собирается перед своей загрузкой, а не при выборе папки. */
export interface ILazyPackage {
  readonly kind: 'folder-package';
  readonly name: string;
  /** Сумма размеров файлов комплекта; размер самого архива известен после сборки. */
  readonly size: number;
  readonly note: string;
  readonly build: () => Promise<File>;
}

export type UploadSource = File | ILazyPackage;

export const isLazyPackage = (source: UploadSource): source is ILazyPackage =>
  'kind' in source && source.kind === 'folder-package';

const readBytes = async (blob: Blob): Promise<Uint8Array> =>
  new Uint8Array(await blob.arrayBuffer());

const packageFiles = (pkg: IFolderPackage): { file: File; compress: boolean }[] => [
  { file: pkg.pdf, compress: false },
  { file: pkg.resultsMd, compress: true },
  { file: pkg.resultsHtml, compress: true },
  { file: pkg.blocks, compress: true },
];

const feed = async (zip: Zip, file: File, compress: boolean): Promise<void> => {
  const entry = compress
    ? new AsyncZipDeflate(file.name, { level: 6 })
    : new ZipPassThrough(file.name);
  zip.add(entry);

  let offset = 0;
  do {
    const end = Math.min(offset + READ_CHUNK_BYTES, file.size);
    const chunk = await readBytes(file.slice(offset, end));
    entry.push(chunk, end >= file.size);
    offset = end;
  } while (offset < file.size);
};

export const buildPackageZip = (pkg: IFolderPackage): Promise<File> =>
  new Promise<File>((resolve, reject) => {
    const parts: BlobPart[] = [];
    const zip = new Zip((error, chunk, final) => {
      if (error) {
        reject(error);
        return;
      }
      parts.push(chunk as BlobPart);
      if (final) resolve(new File(parts, `${pkg.stem}.zip`, { type: 'application/zip' }));
    });

    const run = async () => {
      for (const { file, compress } of packageFiles(pkg)) {
        await feed(zip, file, compress);
      }
      zip.end();
    };

    run().catch((error: unknown) => {
      zip.terminate();
      reject(error instanceof Error ? error : new Error('Не удалось собрать пакет'));
    });
  });

export const toLazyPackage = (pkg: IFolderPackage): ILazyPackage => ({
  kind: 'folder-package',
  name: `${pkg.stem}.zip`,
  size: packageFiles(pkg).reduce((sum, { file }) => sum + file.size, 0),
  note: `пакет из папки: ${PACKAGE_FILE_COUNT} файла`,
  build: () => buildPackageZip(pkg),
});
