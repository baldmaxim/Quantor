import type { IFolderEntry } from '@/lib/uploads/packageFolder';

/**
 * Обход брошенных в окно папок (DataTransferItem.webkitGetAsEntry).
 *
 * `webkitGetAsEntry` нужно вызвать синхронно в обработчике drop — после первого await
 * список элементов уже пуст. Поэтому разбор разделён: grabDroppedEntries — синхронно,
 * readDroppedEntries — потом, асинхронно.
 */

export const grabDroppedEntries = (items: DataTransferItemList): FileSystemEntry[] =>
  Array.from(items).flatMap((item) => {
    const entry = item.kind === 'file' ? item.webkitGetAsEntry() : null;
    return entry ? [entry] : [];
  });

export const hasDirectory = (entries: readonly FileSystemEntry[]): boolean =>
  entries.some((entry) => entry.isDirectory);

const fileOf = (entry: FileSystemFileEntry): Promise<File> =>
  new Promise((resolve, reject) => entry.file(resolve, reject));

/** readEntries отдаёт порциями (~100): читаем, пока не вернётся пустая. */
const childrenOf = async (entry: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> => {
  const reader = entry.createReader();
  const all: FileSystemEntry[] = [];

  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    );
    if (batch.length === 0) return all;
    all.push(...batch);
  }
};

const walk = async (entry: FileSystemEntry, out: IFolderEntry[]): Promise<void> => {
  if (entry.isFile) {
    const file = await fileOf(entry as FileSystemFileEntry);
    out.push({ file, path: entry.fullPath.replace(/^\/+/, '') || file.name });
    return;
  }
  if (entry.isDirectory) {
    for (const child of await childrenOf(entry as FileSystemDirectoryEntry)) {
      await walk(child, out);
    }
  }
};

export const readDroppedEntries = async (
  entries: readonly FileSystemEntry[],
): Promise<IFolderEntry[]> => {
  const out: IFolderEntry[] = [];
  for (const entry of entries) await walk(entry, out);
  return out;
};
