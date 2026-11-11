import type { CadFinishSheetRead, CadFinishTemplateRead } from '@quantor/api-client';

import {
  HEIGHT_SOURCE_LABELS,
  TEMPLATE_SOURCE_LABELS,
  WALLS_UNLINKED_LABEL,
  finishZoneTitle,
} from './finish-sheet';
import { ROOM_TYPE_LABELS, SURFACE_LABELS, basesText } from './room-types';

/**
 * CSV ведомости отделки листа: разделитель «;», запятая в десятичных (так открывает русский
 * Excel), UTF-8 с BOM. Неопределённая величина - пустая ячейка, не 0. Строится на клиенте из уже
 * показанной ведомости; расчётов здесь нет.
 */

export const CSV_BOM = '﻿';

const FORMULA_START = /^[=+\-@\t\r]/;

/** Текстовая ячейка: кавычки по правилам CSV и защита от формул Excel (`=`, `+`, `-`, `@`). */
const textCell = (value: string | null): string => {
  if (value === null || value === '') return '';
  const safe = FORMULA_START.test(value) ? `'${value}` : value;
  return /[;"\n\r]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
};

const numberCell = (value: number | null): string =>
  value === null ? '' : String(Math.round(value * 1000) / 1000).replace('.', ',');

const row = (cells: readonly string[]): string => cells.join(';');

const ZONE_HEADER = [
  'Зона',
  'Тип помещения',
  'Шаблон',
  'Назначение шаблона',
  'Пол, м2',
  'Стены, м2',
  'Потолок, м2',
  'Высота стен, мм',
  'Источник высоты',
  'Привязка стен',
  'Монолит, м',
  'Монолит, м2',
  'Кладка, м',
  'Кладка, м2',
  'ГКЛ, м',
  'ГКЛ, м2',
  'Двери, м',
  'Двери над проёмами, м2',
  'Проёмы без двери, м',
  'Без стены, м',
  'Откосы, м',
  'Откосы, м2',
  'Поверхность',
  'Работа',
  'Материал',
  'Раз',
  'Толщина, мм',
  'Основания',
  'Площадь слоя, м2',
  'Количество материала',
  'Ед.',
];

const TOTALS_HEADER = [
  'Поверхность',
  'Работа',
  'Материал',
  'Площадь, м2',
  'Количество материала',
  'Ед.',
  'Зон',
];

const ROOM_TYPE_HEADER = ['Тип помещения', 'Зон', 'Пол, м2', 'Стены, м2', 'Потолок, м2'];

/** Текст CSV: зоны со слоями, затем итоги по слоям и по типам помещений. */
export const buildFinishCsv = (
  sheet: CadFinishSheetRead,
  templates: readonly CadFinishTemplateRead[],
): string => {
  const lines: string[] = [row(ZONE_HEADER)];

  for (const zone of sheet.zones) {
    const template =
      zone.template_id === null ? null : templates.find((t) => t.id === zone.template_id);
    const head = [
      textCell(finishZoneTitle(zone)),
      textCell(zone.room_type === null ? null : ROOM_TYPE_LABELS[zone.room_type]),
      textCell(template?.name ?? null),
      textCell(zone.template_source === null ? null : TEMPLATE_SOURCE_LABELS[zone.template_source]),
      numberCell(zone.floor_area_m2),
      numberCell(zone.wall_area_m2),
      numberCell(zone.ceiling_area_m2),
      numberCell(zone.wall_height_mm),
      textCell(
        zone.wall_height_source === null ? null : HEIGHT_SOURCE_LABELS[zone.wall_height_source],
      ),
      textCell(zone.walls_breakdown.linked ? 'по конструкциям' : WALLS_UNLINKED_LABEL),
      numberCell(zone.walls_breakdown.monolith_m),
      numberCell(zone.walls_breakdown.area_by_base.monolith),
      numberCell(zone.walls_breakdown.masonry_m),
      numberCell(zone.walls_breakdown.area_by_base.masonry),
      numberCell(zone.walls_breakdown.gkl_m),
      numberCell(zone.walls_breakdown.area_by_base.gkl),
      numberCell(zone.walls_breakdown.door_m),
      numberCell(zone.walls_breakdown.door_over_area_m2),
      numberCell(zone.walls_breakdown.gap_m),
      numberCell(zone.walls_breakdown.open_m),
      numberCell(zone.walls_breakdown.reveal_m),
      numberCell(zone.walls_breakdown.reveal_area_m2),
    ];
    if (zone.layers.length === 0) {
      lines.push(row([...head, ...Array<string>(ZONE_HEADER.length - head.length).fill('')]));
      continue;
    }
    for (const layer of zone.layers) {
      lines.push(
        row([
          ...head,
          textCell(SURFACE_LABELS[layer.surface]),
          textCell(layer.work),
          textCell(layer.material),
          String(layer.coats),
          numberCell(layer.thickness_mm),
          textCell(basesText(layer.bases)),
          numberCell(layer.area_m2),
          numberCell(layer.material_qty),
          textCell(layer.material_unit),
        ]),
      );
    }
  }

  lines.push('', row([textCell('Итого по слоям')]), row(TOTALS_HEADER));
  for (const total of sheet.totals) {
    lines.push(
      row([
        textCell(SURFACE_LABELS[total.surface]),
        textCell(total.work),
        textCell(total.material),
        numberCell(total.area_m2),
        numberCell(total.material_qty),
        textCell(total.material_unit),
        String(total.zone_count),
      ]),
    );
  }

  lines.push('', row([textCell('Итого по типам помещений')]), row(ROOM_TYPE_HEADER));
  for (const item of sheet.by_room_type) {
    lines.push(
      row([
        textCell(ROOM_TYPE_LABELS[item.room_type]),
        String(item.zone_count),
        numberCell(item.floor_area_m2),
        numberCell(item.wall_area_m2),
        numberCell(item.ceiling_area_m2),
      ]),
    );
  }

  return `${CSV_BOM}${lines.join('\r\n')}\r\n`;
};

/** Имя файла: номер страницы с 1. */
export const finishCsvFilename = (pageIndex: number): string => `otdelka-list-${pageIndex + 1}.csv`;

/** Скачивание текста файлом через временную ссылку; адрес сразу освобождается. */
export const downloadCsv = (name: string, text: string): void => {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};
