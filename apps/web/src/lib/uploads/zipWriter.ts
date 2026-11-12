import { deflate } from 'fflate';

/**
 * Минимальный потоковый ZIP-писатель без ZIP64.
 *
 * Итоговый Blob собирается из ссылок: несжатый файл (PDF) вставляется как сам Blob, браузер
 * не копирует его в память. CRC32 считается чтением file.slice кусками, куски не копятся.
 * Размеры и CRC пишутся в local header (data descriptor не используется).
 */

export const READ_CHUNK_BYTES = 4 * 1024 * 1024;

const ZIP_LIMIT = 0xffffffff;
const SIZE_ERROR = 'Пакет больше 4 ГБ — загрузите ZIP вручную';
const FLAG_UTF8 = 0x0800;
const VERSION = 20;
const METHOD_STORED = 0;
const METHOD_DEFLATE = 8;

export interface IZipEntry {
  readonly name: string;
  readonly file: Blob;
  readonly compress: boolean;
  /** Миллисекунды, как File.lastModified. */
  readonly lastModified: number;
}

let crcTable: Uint32Array | null = null;

const getCrcTable = (): Uint32Array => {
  if (crcTable) return crcTable;
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  crcTable = table;
  return table;
};

/** Промежуточное состояние CRC32 (без финальной инверсии). */
const crcUpdate = (state: number, bytes: Uint8Array): number => {
  const table = getCrcTable();
  let c = state;
  for (let i = 0; i < bytes.length; i += 1) {
    c = (table[(c ^ (bytes[i] ?? 0)) & 0xff] ?? 0) ^ (c >>> 8);
  }
  return c >>> 0;
};

export const crc32 = (bytes: Uint8Array): number => (crcUpdate(0xffffffff, bytes) ^ 0xffffffff) >>> 0;

/** CRC32 Blob потоковым чтением кусками; куски не накапливаются. */
export const crc32Blob = async (blob: Blob): Promise<number> => {
  let state = 0xffffffff;
  for (let offset = 0; offset < blob.size; offset += READ_CHUNK_BYTES) {
    const chunk = new Uint8Array(
      await blob.slice(offset, Math.min(offset + READ_CHUNK_BYTES, blob.size)).arrayBuffer(),
    );
    state = crcUpdate(state, chunk);
  }
  return (state ^ 0xffffffff) >>> 0;
};

const deflateAsync = (data: Uint8Array): Promise<Uint8Array> =>
  new Promise<Uint8Array>((resolve, reject) => {
    deflate(data, { level: 6 }, (error, result) => {
      if (error) reject(error);
      else resolve(result);
    });
  });

/** Время и дата в формате MS-DOS (локальное время, год от 1980, секунды / 2). */
export const toDosDateTime = (ms: number): { time: number; date: number } => {
  const d = new Date(ms);
  const year = d.getFullYear();
  if (!Number.isFinite(year) || year < 1980) return { time: 0, date: (1 << 5) | 1 };
  const date = ((Math.min(year, 2107) - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
  const time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
  return { time, date };
};

const makeHeader = (size: number): { bytes: Uint8Array<ArrayBuffer>; view: DataView } => {
  const bytes = new Uint8Array(size);
  return { bytes, view: new DataView(bytes.buffer) };
};

interface IPreparedEntry {
  readonly nameBytes: Uint8Array;
  readonly method: number;
  readonly crc: number;
  readonly size: number;
  readonly compressedSize: number;
  readonly data: BlobPart;
  readonly time: number;
  readonly date: number;
}

const prepare = async (entry: IZipEntry): Promise<IPreparedEntry> => {
  const nameBytes = new TextEncoder().encode(entry.name);
  const { time, date } = toDosDateTime(entry.lastModified);
  if (entry.file.size >= ZIP_LIMIT) throw new Error(SIZE_ERROR);

  if (entry.compress) {
    const raw = new Uint8Array(await entry.file.arrayBuffer());
    const packed = await deflateAsync(raw);
    return {
      nameBytes,
      method: METHOD_DEFLATE,
      crc: crc32(raw),
      size: raw.length,
      compressedSize: packed.length,
      data: packed as BlobPart,
      time,
      date,
    };
  }
  return {
    nameBytes,
    method: METHOD_STORED,
    crc: await crc32Blob(entry.file),
    size: entry.file.size,
    compressedSize: entry.file.size,
    data: entry.file,
    time,
    date,
  };
};

const localHeader = (e: IPreparedEntry): Uint8Array<ArrayBuffer> => {
  const { bytes, view } = makeHeader(30 + e.nameBytes.length);
  view.setUint32(0, 0x04034b50, true);
  view.setUint16(4, VERSION, true);
  view.setUint16(6, FLAG_UTF8, true);
  view.setUint16(8, e.method, true);
  view.setUint16(10, e.time, true);
  view.setUint16(12, e.date, true);
  view.setUint32(14, e.crc, true);
  view.setUint32(18, e.compressedSize, true);
  view.setUint32(22, e.size, true);
  view.setUint16(26, e.nameBytes.length, true);
  view.setUint16(28, 0, true);
  bytes.set(e.nameBytes, 30);
  return bytes;
};

const centralHeader = (e: IPreparedEntry, localOffset: number): Uint8Array<ArrayBuffer> => {
  const { bytes, view } = makeHeader(46 + e.nameBytes.length);
  view.setUint32(0, 0x02014b50, true);
  view.setUint16(4, VERSION, true);
  view.setUint16(6, VERSION, true);
  view.setUint16(8, FLAG_UTF8, true);
  view.setUint16(10, e.method, true);
  view.setUint16(12, e.time, true);
  view.setUint16(14, e.date, true);
  view.setUint32(16, e.crc, true);
  view.setUint32(20, e.compressedSize, true);
  view.setUint32(24, e.size, true);
  view.setUint16(28, e.nameBytes.length, true);
  view.setUint32(42, localOffset, true);
  bytes.set(e.nameBytes, 46);
  return bytes;
};

const endOfCentralDirectory = (
  count: number,
  cdSize: number,
  cdOffset: number,
): Uint8Array<ArrayBuffer> => {
  const { bytes, view } = makeHeader(22);
  view.setUint32(0, 0x06054b50, true);
  view.setUint16(8, count, true);
  view.setUint16(10, count, true);
  view.setUint32(12, cdSize, true);
  view.setUint32(16, cdOffset, true);
  return bytes;
};

/** Собирает ZIP из записей; несжатые файлы вставляются в результат ссылками. */
export const buildZipFile = async (
  entries: readonly IZipEntry[],
  zipName: string,
): Promise<File> => {
  const parts: BlobPart[] = [];
  const central: Uint8Array<ArrayBuffer>[] = [];
  let offset = 0;

  for (const entry of entries) {
    const prepared = await prepare(entry);
    const header = localHeader(prepared);
    central.push(centralHeader(prepared, offset));
    parts.push(header, prepared.data);
    offset += header.length + prepared.compressedSize;
    if (offset >= ZIP_LIMIT) throw new Error(SIZE_ERROR);
  }

  const cdSize = central.reduce((sum, c) => sum + c.length, 0);
  parts.push(...central, endOfCentralDirectory(entries.length, cdSize, offset));
  return new File(parts, zipName, { type: 'application/zip' });
};
