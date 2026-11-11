import type { DocumentKind } from '@quantor/api-client';

/**
 * Разделы проектной документации для списка документов проекта.
 *
 * В API нет поля «раздел»: его определяют по шифру в имени файла (`…-П-ИОС2.1_ver4.pdf`).
 * Это только подпись и группировка для отображения: ничего не меняется и не удаляется,
 * а неузнанный шифр честно попадает в «Прочее».
 */

export type SectionId =
  | 'general'
  | 'surveys'
  | 'ar'
  | 'kr'
  | 'ios1'
  | 'ios2'
  | 'ios3'
  | 'ios4'
  | 'ios5'
  | 'ios6'
  | 'ios7'
  | 'pzu'
  | 'pos'
  | 'oos'
  | 'pb'
  | 'odi'
  | 'ee'
  | 'sm'
  | 'tables'
  | 'bim'
  | 'other'
  | 'packages';

/** Порядок групп: как в составе проекта; пакеты распознавания — внизу. */
export const SECTION_ORDER: readonly SectionId[] = [
  'general',
  'surveys',
  'ar',
  'kr',
  'ios1',
  'ios2',
  'ios3',
  'ios4',
  'ios5',
  'ios6',
  'ios7',
  'pzu',
  'pos',
  'oos',
  'pb',
  'odi',
  'ee',
  'sm',
  'tables',
  'bim',
  'other',
  'packages',
];

export const SECTION_TITLES: Readonly<Record<SectionId, string>> = {
  general: 'Общая часть: ПЗ, состав проекта, ИРД',
  surveys: 'Инженерные изыскания',
  ar: 'Архитектурные решения',
  kr: 'Конструктивные решения',
  ios1: 'Электроснабжение (ИОС1)',
  ios2: 'Водоснабжение и пожаротушение (ИОС2)',
  ios3: 'Водоотведение (ИОС3)',
  ios4: 'Отопление, вентиляция, кондиционирование (ИОС4)',
  ios5: 'Сети связи (ИОС5)',
  ios6: 'Технологические решения (ИОС6)',
  ios7: 'Газоснабжение (ИОС7)',
  pzu: 'Генплан и ПЗУ',
  pos: 'Организация строительства',
  oos: 'Охрана окружающей среды',
  pb: 'Пожарная безопасность',
  odi: 'Доступ маломобильных групп',
  ee: 'Энергоэффективность',
  sm: 'Смета на строительство',
  tables: 'Ведомости и таблицы',
  bim: 'Модели BIM',
  other: 'Прочее',
  packages: 'Пакеты распознавания',
};

/** Шифр (латиница уже приведена к кириллице, регистр верхний) → раздел. */
const CODE_SECTIONS: Readonly<Record<string, SectionId>> = {
  АР: 'ar',
  КР: 'kr',
  КЖ: 'kr',
  КМ: 'kr',
  ЭОМ: 'ios1',
  ЭС: 'ios1',
  ВК: 'ios2',
  В: 'ios2',
  К: 'ios3',
  ОВ: 'ios4',
  ОВИК: 'ios4',
  СС: 'ios5',
  ТХ: 'ios6',
  ГС: 'ios7',
  ПЗУ: 'pzu',
  ГП: 'pzu',
  ПОС: 'pos',
  ООС: 'oos',
  ПБ: 'pb',
  МПБ: 'pb',
  ОДИ: 'odi',
  ЭЭ: 'ee',
  ЭЭФ: 'ee',
  СМ: 'sm',
  ПЗ: 'general',
  СП: 'general',
  ИРД: 'general',
  ИГДИ: 'surveys',
  ИГИ: 'surveys',
  ИЭИ: 'surveys',
  ИГМИ: 'surveys',
};

const IOS_SECTIONS: Readonly<Record<string, SectionId>> = {
  '1': 'ios1',
  '2': 'ios2',
  '3': 'ios3',
  '4': 'ios4',
  '5': 'ios5',
  '6': 'ios6',
  '7': 'ios7',
};

/** Знаки стадии: за ними в имени идёт шифр раздела. */
const STAGE_MARKS: ReadonlySet<string> = new Set(['П', 'ПД', 'Р', 'РД']);

const BIM_KINDS: ReadonlySet<DocumentKind> = new Set(['revit', 'navisworks', 'ifc']);
const BIM_EXTENSIONS: ReadonlySet<string> = new Set(['rvt', 'ifc', 'nwd', 'nwc']);
const TABLE_EXTENSIONS: ReadonlySet<string> = new Set(['xlsx', 'xls', 'csv']);

/** Латинские двойники кириллических букв: «AP» из латиницы читается как «АР». */
const LATIN_TO_CYRILLIC: Readonly<Record<string, string>> = {
  A: 'А',
  B: 'В',
  C: 'С',
  E: 'Е',
  H: 'Н',
  K: 'К',
  M: 'М',
  O: 'О',
  P: 'Р',
  T: 'Т',
  X: 'Х',
};

const normalizeLetters = (letters: string): string =>
  Array.from(letters.toUpperCase(), (char) => LATIN_TO_CYRILLIC[char] ?? char).join('');

// Границы слова вручную: `\b` в JS не знает кириллицу. Буквы 1–4, затем необязательный номер
// подраздела («1.1», «2.3»); соседние буквы и цифры слово не обрывают, поэтому «КАМ0925» и
// «МЛДГВ» шифром не считаются.
const TOKEN = /(?<![\p{L}\p{N}])(\p{L}{1,4})(\d+(?:\.\d+)*)?(?![\p{L}\p{N}])/gu;
const EXTENSION = /\.([A-Za-z0-9]{2,5})$/;
const VOR = /(?<![\p{L}])вор(?![\p{L}])|смет|ведомост/iu;

export const fileExtension = (name: string): string =>
  EXTENSION.exec(name)?.[1]?.toLowerCase() ?? '';

/** Имя без расширения: по нему пакет сопоставляется с PDF. */
export const baseName = (name: string): string => name.replace(EXTENSION, '');

interface IToken {
  readonly letters: string;
  readonly number: string;
  /** Подпись подраздела как в шифре: «ИОС2.1». */
  readonly label: string;
}

const tokens = (name: string): IToken[] =>
  Array.from(baseName(name).matchAll(TOKEN), (match) => {
    const letters = normalizeLetters(match[1] ?? '');
    const number = match[2] ?? '';
    return { letters, number, label: `${letters}${number}` };
  });

const tokenSection = ({ letters, number }: IToken): SectionId | null => {
  // У ИОС раздел задаёт первая цифра номера: «ИОС2.3» — ВК, «ИОС3.2» — водоотведение.
  if (letters === 'ИОС') return IOS_SECTIONS[number.charAt(0)] ?? null;
  return CODE_SECTIONS[letters] ?? null;
};

export interface ISectionInfo {
  readonly section: SectionId;
  /** Шифр с подразделом («ИОС2.1»); `null`, когда раздел определён не по шифру. */
  readonly code: string | null;
}

export const isRecognizedPackage = (name: string, kind: DocumentKind): boolean =>
  kind === 'recognized_package' || fileExtension(name) === 'zip';

/**
 * Раздел документа по имени и виду. Порядок: BIM → ведомости → шифр после знака стадии
 * («-П-», «-РД-») → шифр в любом месте имени → «Прочее».
 */
export const documentSection = (name: string, kind: DocumentKind): ISectionInfo => {
  const extension = fileExtension(name);
  if (BIM_KINDS.has(kind) || BIM_EXTENSIONS.has(extension)) return { section: 'bim', code: null };
  if (TABLE_EXTENSIONS.has(extension) || VOR.test(baseName(name))) {
    return { section: 'tables', code: null };
  }

  const found = tokens(name);
  const stage = found.findIndex((token) => token.number === '' && STAGE_MARKS.has(token.letters));
  const candidates = stage >= 0 ? [...found.slice(stage + 1), ...found] : found;

  for (const token of candidates) {
    const section = tokenSection(token);
    if (section !== null) return { section, code: token.label };
  }
  return { section: 'other', code: null };
};

/** Минимальный набор полей документа, нужный для группировки. */
export interface ISectionDocument {
  readonly id: string;
  readonly display_name: string;
  readonly document_kind: DocumentKind;
}

export interface ISectionEntry<T extends ISectionDocument> {
  readonly document: T;
  /** Распознанные пакеты того же базового имени, скрытые в строке этого документа. */
  readonly packages: readonly T[];
  readonly code: string | null;
}

export interface ISectionGroup<T extends ISectionDocument> {
  readonly id: SectionId;
  readonly title: string;
  readonly entries: readonly ISectionEntry<T>[];
}

const nameKey = (name: string): string => baseName(name).toLowerCase();

/**
 * Группировка документов по разделам с привязкой пакетов к PDF.
 *
 * Пакет, у которого есть PDF того же имени (без расширения), не получает своей строки —
 * он учитывается у PDF. Остальные пакеты собираются в группу «Пакеты распознавания».
 * Порядок документов внутри группы сохраняется, пустые группы не возвращаются.
 */
export const groupDocuments = <T extends ISectionDocument>(
  documents: readonly T[],
): ISectionGroup<T>[] => {
  const isPackage = (document: T): boolean =>
    isRecognizedPackage(document.display_name, document.document_kind);

  const pdfByKey = new Map<string, T>();
  for (const document of documents) {
    if (document.document_kind !== 'pdf' || isPackage(document)) continue;
    const key = nameKey(document.display_name);
    if (!pdfByKey.has(key)) pdfByKey.set(key, document);
  }

  const attached = new Map<string, T[]>();
  const orphans: T[] = [];
  for (const document of documents) {
    if (!isPackage(document)) continue;
    const owner = pdfByKey.get(nameKey(document.display_name));
    if (owner) attached.set(owner.id, [...(attached.get(owner.id) ?? []), document]);
    else orphans.push(document);
  }

  const buckets = new Map<SectionId, ISectionEntry<T>[]>();
  const push = (section: SectionId, entry: ISectionEntry<T>): void => {
    buckets.set(section, [...(buckets.get(section) ?? []), entry]);
  };

  for (const document of documents) {
    if (isPackage(document)) continue;
    const { section, code } = documentSection(document.display_name, document.document_kind);
    push(section, { document, packages: attached.get(document.id) ?? [], code });
  }
  for (const document of orphans) push('packages', { document, packages: [], code: null });

  return SECTION_ORDER.flatMap((id) => {
    const entries = buckets.get(id);
    return entries && entries.length > 0 ? [{ id, title: SECTION_TITLES[id], entries }] : [];
  });
};
