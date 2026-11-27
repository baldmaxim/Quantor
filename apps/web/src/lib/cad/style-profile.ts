import type { CadStylePreviewResult, CadStyleSample } from '@quantor/api-client';
import { z } from 'zod';

/**
 * Профиль оформления тома, снятый по щелчкам-образцам (ADR-0049, решения 3, 6, 7).
 *
 * Здесь - чистая логика образцов и разбор `preview`. Сервер отдаёт `preview` свободным словарём
 * (схема движка `cad_engine.style_preview.v1`): форму держит движок, поэтому на входе она
 * проверяется Zod. Остальные типы (образец, результат, версия) приходят из сгенерированного
 * клиента.
 */

export type StyleClass = CadStyleSample['class'];

export interface IStyleClassInfo {
  readonly id: StyleClass;
  readonly label: string;
  /** Движок пока не снимает поле этого класса: образец принимается, на профиль не влияет. */
  readonly engineSupported: boolean;
  /** Цвет маркера на листе. */
  readonly color: string;
}

/** Классы образцов в порядке выбора в панели. */
export const STYLE_CLASSES: readonly IStyleClassInfo[] = [
  { id: 'monolith', label: 'Монолит', engineSupported: true, color: '#d9480f' },
  { id: 'shaft', label: 'Шахта', engineSupported: true, color: '#7048e8' },
  { id: 'masonry', label: 'Кладка', engineSupported: true, color: '#0b7285' },
  { id: 'door', label: 'Дверь', engineSupported: true, color: '#2b8a3e' },
  { id: 'insulation', label: 'Утеплитель', engineSupported: false, color: '#c2255c' },
  { id: 'dimension_tick', label: 'Засечка размера', engineSupported: false, color: '#5c7cfa' },
];

export const styleClassInfo = (id: StyleClass): IStyleClassInfo => {
  const found = STYLE_CLASSES.find((item) => item.id === id);
  if (!found) throw new Error(`Неизвестный класс образца: ${id}`);
  return found;
};

export const styleClassLabel = (id: string): string =>
  STYLE_CLASSES.find((item) => item.id === id)?.label ?? id;

/** Предел образцов в одном предпросмотре (контракт сервера). */
export const MAX_STYLE_SAMPLES = 200;

export type StyleSample = CadStyleSample;

/** Добавить образец; сверх предела список не меняется (тот же массив). */
export const addStyleSample = (
  samples: readonly StyleSample[],
  sample: StyleSample,
): readonly StyleSample[] =>
  samples.length >= MAX_STYLE_SAMPLES ? samples : [...samples, sample];

export const removeStyleSample = (
  samples: readonly StyleSample[],
  index: number,
): readonly StyleSample[] => samples.filter((_, position) => position !== index);

/** Номер образца своего класса (с 1) - подпись в списке и на маркере. */
export const sampleOrdinal = (samples: readonly StyleSample[], index: number): number => {
  const own = samples[index];
  if (!own) return 0;
  return samples.slice(0, index + 1).filter((item) => item.class === own.class).length;
};

// ------------------------------------------------------------------ разбор preview

const grays = z.array(z.number());
const count = z.number();

const areaClass = z.object({
  grays,
  fills: count,
  area_pt2: z.number().nullable().optional(),
  area_m2: z.number().nullable().optional(),
});

const hatchSignature = z.object({
  color: z.array(z.number()),
  pen: z.number(),
  angle_deg: z.number(),
  pitch_pt: z.number(),
});

const monolithClass = areaClass.extend({
  hatch_signatures: z.array(hatchSignature).optional(),
  hatch_segments: count.optional(),
});

const sampleRecord = z
  .object({ index: z.number().optional(), class: z.string() })
  .passthrough();

export const stylePreviewSchema = z.object({
  classes: z
    .object({
      monolith: monolithClass,
      shaft: areaClass,
      masonry: z.object({ grays, hatch_segments: count }),
      door: z.object({ pen_max_width: z.number(), candidates_not_doors: count }),
    })
    .nullable(),
  field_sources: z.record(z.string(), z.string()).nullable(),
  unclassified_fill_share: z.number().min(0).max(1).nullable(),
  rejected_samples: z.array(z.object({ sample: sampleRecord, reason: z.string() }).passthrough()),
  outline_only_samples: z
    .array(z.object({ sample: sampleRecord, reason: z.string(), area_pt2: z.number() }).passthrough())
    .optional(),
  unsupported_samples: z.array(sampleRecord.extend({ reason: z.string() }).passthrough()),
  warnings: z.array(z.object({ code: z.string(), message: z.string() }).passthrough()),
});

export type StyleHatchSignature = z.infer<typeof hatchSignature>;
export type StylePreview = z.infer<typeof stylePreviewSchema>;

/** Разобрать `preview` результата; не по контракту - `null` (панель скажет, что разбора нет). */
export const parseStylePreview = (raw: unknown): StylePreview | null => {
  const parsed = stylePreviewSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
};

// ------------------------------------------------------------------ тексты

const REJECT_REASONS: Readonly<Record<string, string>> = {
  no_fill_at_point: 'в точке нет заливки',
  color_fill_unsupported: 'цветная заливка: движок снимает только серые',
  no_hatch_at_point: 'в точке нет штриховки',
  color_hatch_unsupported: 'цветная штриховка: движок снимает только серую',
  no_arc_at_point: 'в точке нет дуги двери',
  no_fill_or_hatch_at_point: 'Ни заливки, ни штриховки в точке',
};

export const rejectReasonText = (reason: string): string => REJECT_REASONS[reason] ?? reason;

const SCALE_SOURCES: Readonly<Record<CadStylePreviewResult['scale_source'], string>> = {
  calibration: 'калибровка листа',
  cad_auto: 'автомасштаб преобразования',
  none: 'не определён',
};

export const scaleSourceText = (source: CadStylePreviewResult['scale_source']): string =>
  SCALE_SOURCES[source];

/** Площадь класса: м² или честное «не определена»; ноль не подставляется. */
export const areaText = (areaM2: number | null | undefined): string =>
  typeof areaM2 === 'number'
    ? `${areaM2.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} м²`
    : 'площадь не определена: нет масштаба листа';

/** Доля неразобранных заливок в процентах; нет значения - «—». */
export const shareText = (share: number | null): string =>
  share === null ? '—' : `${(share * 100).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} %`;

export const STATUS_TEXT: Readonly<Record<CadStylePreviewResult['result_status'], string>> = {
  profile: 'Профиль снят',
  no_signature: 'Признаков не найдено',
  profile_out_of_limits: 'Профиль вне допустимых пределов',
};

export const NO_SIGNATURE_HINT =
  'Ни один щелчок не дал признака. Монолит — внутри заливки или по штриховке стены, шахту — внутри заливки, кладку — по штриховке, дверь — по дуге или внутри сектора открывания.';

/** Цвет подписи штриховки (доли 0..1) в CSS `rgb()`; вне диапазона зажимается. */
export const hatchColorCss = (color: readonly number[]): string => {
  const [red = 0, green = 0, blue = 0] = color.map((part) =>
    Math.round(Math.min(1, Math.max(0, part)) * 255),
  );
  return `rgb(${red}, ${green}, ${blue})`;
};

const decimal = (value: number): string =>
  value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });

/** Подпись штриховки текстом: угол, шаг и перо в pt. */
export const hatchSignatureText = (item: StyleHatchSignature): string =>
  `угол ${decimal(item.angle_deg)}°, шаг ${decimal(item.pitch_pt)} pt, перо ${decimal(item.pen)} pt`;

/** Откуда профиль: из `source.kind` версии. */
export const profileSourceText = (source: Readonly<Record<string, unknown>>): string => {
  if (source.kind === 'samples') {
    const page = source.page_index;
    return typeof page === 'number' ? `по образцам, лист ${page + 1}` : 'по образцам';
  }
  if (source.kind === 'manual') return 'вручную';
  return 'источник не указан';
};
