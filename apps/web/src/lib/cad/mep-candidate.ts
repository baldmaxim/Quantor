import { z } from 'zod';

/**
 * `candidate.json` трасс механики (схема `quantor.cad_mep.candidate.v1`).
 *
 * Это файл-артефакт задания, а не DTO API: его форму держит генератор (cad_mep из репозитория
 * движка), здесь она проверяется на входе. Читается только то, что показывает панель;
 * остальные поля файла (шахты, помещения, проверки, происхождение) пропускаются. Файл -
 * кандидат: до принятия человеком в расчёт не идёт.
 */

/** Каталог вида в артефактах: страница и вид с 1 (`views/p081_v01`), как у сервера. */
export const viewFolder = (pageIndex: number, view: number): string =>
  `views/p${String(pageIndex + 1).padStart(3, '0')}_v${String(view).padStart(2, '0')}`;

export const CANDIDATE_SCHEMA = 'quantor.cad_mep.candidate.v1';

/**
 * Длина трасс - одна расчётная величина: длина по оси с вертикальными участками (`len3d_m`
 * генератора). Проекция на план (`plan_m`) - не количество, а свойство вида: не читается.
 */
const lengthSchema = z
  .object({ len3d_m: z.number() })
  .transform(({ len3d_m }) => ({ length_m: len3d_m }));
const sourcedSchema = z.object({ value: z.number(), source: z.string() });
/** Отметка пола / высота этажа в происхождении: значение, источник и цитата из документации. */
const provenanceValueSchema = z.object({
  value_mm: z.number(),
  source: z.string(),
  evidence: z.string().default(''),
});

const candidateSchema = z.object({
  schema: z.literal(CANDIDATE_SCHEMA),
  status: z.string(),
  provenance: z
    .object({
      floor_elevation: provenanceValueSchema.optional(),
      floor_height: provenanceValueSchema.optional(),
    })
    .optional(),
  elevation: z.object({
    floor_elevation_mm: sourcedSchema,
    floor_height_mm: sourcedSchema,
    sheet_marks_mm: z.array(z.number()).default([]),
  }),
  assumptions: z
    .array(
      z.object({
        name: z.string(),
        value: z.unknown(),
        unit: z.string().nullable().optional(),
        note: z.string().nullable().optional(),
      }),
    )
    .default([]),
  apartments: z
    .array(
      z.object({
        idx: z.number(),
        number: z.string().nullable().optional(),
        lengths_own_lines: z.record(z.string(), lengthSchema).default({}),
      }),
    )
    .default([]),
  routes: z.object({
    /** Система каждого слоя по генератору (`routes.layers`); у старых файлов нет. */
    layers: z.record(z.string(), z.object({ system: z.string() })).default({}),
    by_layer: z.record(z.string(), lengthSchema).default({}),
    /** Длина слоя по диаметру (`by_dn_mm`, ключ - Ø в мм) и сечению (`by_size`: «AxB» или «ØD»). */
    by_layer_dims: z
      .record(
        z.string(),
        z.object({
          by_dn_mm: z.record(z.string(), lengthSchema).default({}),
          by_size: z.record(z.string(), lengthSchema).default({}),
        }),
      )
      .default({}),
    by_system: z.record(z.string(), lengthSchema).default({}),
    totals: lengthSchema,
  }),
  issues: z
    .array(
      z.object({
        code: z.string(),
        message: z.string(),
        apartment: z.union([z.string(), z.number()]).nullable().optional(),
      }),
    )
    .default([]),
  notes: z.array(z.string()).default([]),
});

export type MepCandidate = z.infer<typeof candidateSchema>;
export type MepLength = z.output<typeof lengthSchema>;

/** Разбор файла; чужая схема или битая форма - `null` (вызывающий скажет об этом человеку). */
export const parseCandidate = (raw: unknown): MepCandidate | null => {
  const parsed = candidateSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
};

/** Источники отметки и высоты: подписи для человека. */
export const FLOOR_SOURCE_LABELS: Readonly<Record<string, string>> = {
  observed: 'из документации',
  derived: 'по соседним этажам',
  operator: 'введено вручную',
};

export const floorSourceLabel = (source: string | null | undefined): string =>
  (source && FLOOR_SOURCE_LABELS[source]) || 'источник не указан';

/** Замечания генератора о расхождении с документацией: показываются заметнее прочих. */
export const isFloorMismatch = (code: string): boolean =>
  code === 'elevation_mismatch' || code === 'floor_height_mismatch';

/** Системы в порядке показа и их названия. */
export const MEP_SYSTEMS: readonly { readonly key: string; readonly label: string }[] = [
  { key: 'heating', label: 'Отопление' },
  { key: 'water', label: 'Водоснабжение' },
  { key: 'fire', label: 'Пожаротушение' },
  { key: 'sewer', label: 'Канализация' },
  { key: 'storm', label: 'Водосток' },
  { key: 'drain', label: 'Дренаж' },
  { key: 'vent', label: 'Вентиляция' },
  { key: 'smoke', label: 'Противодымная вентиляция' },
  { key: 'cooling', label: 'Кондиционирование' },
];

export const mepSystemLabel = (key: string): string =>
  MEP_SYSTEMS.find((item) => item.key === key)?.label ?? key;

/** Значение допущения для показа: число, строка или короткий JSON. */
export const assumptionValueText = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value) ?? '';
  } catch {
    return '';
  }
};

/** Метры с двумя знаками, запятая как разделитель. */
export const formatMeters = (value: number): string =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
