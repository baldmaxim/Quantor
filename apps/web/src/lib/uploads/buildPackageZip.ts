import type { IFolderPackage } from '@/lib/uploads/packageFolder';
import { buildZipFile } from '@/lib/uploads/zipWriter';

/**
 * Сборка ZIP пакета legacy-v1 в браузере.
 *
 * Файлы лежат в корне архива под исходными именами. Писатель — zipWriter.ts: PDF кладётся
 * без сжатия как ссылка на исходный File (в память вкладки не читается, CRC считается кусками),
 * тексты сжимаются в воркере fflate.
 */

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

const packageFiles = (pkg: IFolderPackage): { file: File; compress: boolean }[] => [
  { file: pkg.pdf, compress: false },
  { file: pkg.resultsMd, compress: true },
  { file: pkg.resultsHtml, compress: true },
  { file: pkg.blocks, compress: true },
];

export const buildPackageZip = (pkg: IFolderPackage): Promise<File> =>
  buildZipFile(
    packageFiles(pkg).map(({ file, compress }) => ({
      name: file.name,
      file,
      compress,
      lastModified: file.lastModified,
    })),
    `${pkg.stem}.zip`,
  );

export const toLazyPackage = (pkg: IFolderPackage): ILazyPackage => ({
  kind: 'folder-package',
  name: `${pkg.stem}.zip`,
  size: packageFiles(pkg).reduce((sum, { file }) => sum + file.size, 0),
  note: `пакет из папки: ${PACKAGE_FILE_COUNT} файла`,
  build: () => buildPackageZip(pkg),
});
