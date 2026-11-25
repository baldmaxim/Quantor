import type { AiVorMapSuggestionRead, CadVorLinkRead } from '@quantor/api-client';

/**
 * ИИ-сопоставление ВОР: чистые функции без сети и React. Предложения модели - только кандидаты;
 * связь создаёт человек существующим запросом `PUT .../cad/vor/links/{group_key}`, который
 * ЗАМЕНЯЕТ набор строк группы, поэтому к новой строке добавляются уже связанные.
 */

export const CONFIDENCE_LABELS: Readonly<Record<AiVorMapSuggestionRead['confidence'], string>> = {
  high: 'Высокая',
  medium: 'Средняя',
  low: 'Низкая',
};

/** Цвет уверенности - только токены темы. */
export const CONFIDENCE_CLASSES: Readonly<Record<AiVorMapSuggestionRead['confidence'], string>> = {
  high: 'text-success',
  medium: 'text-warning',
  low: 'text-muted',
};

export interface IAcceptStep {
  readonly groupKey: string;
  /** Полный набор строк группы после принятия: прежние связи плюс принятые. */
  readonly itemIds: readonly string[];
}

/** Предложение имеет хотя бы один объект, с которым строка ещё не связана. */
export const hasUnlinked = (suggestion: AiVorMapSuggestionRead): boolean =>
  suggestion.objects.some((object) => !object.linked);

/**
 * План принятия: по одному шагу на объект (ключ группы). Уже связанные пары пропускаются,
 * прежние связи группы сохраняются.
 */
export const planAccept = (
  suggestions: readonly AiVorMapSuggestionRead[],
  links: readonly CadVorLinkRead[],
): IAcceptStep[] => {
  const added = new Map<string, string[]>();
  for (const suggestion of suggestions) {
    for (const object of suggestion.objects) {
      if (object.linked) continue;
      const ids = added.get(object.group_key) ?? [];
      if (!ids.includes(suggestion.item.id)) ids.push(suggestion.item.id);
      added.set(object.group_key, ids);
    }
  }
  return [...added].map(([groupKey, ids]) => {
    const existing = links
      .filter((link) => link.group_key === groupKey)
      .map((link) => link.item.id);
    return { groupKey, itemIds: [...new Set([...existing, ...ids])] };
  });
};
