/** Области личного токена: для чего он выдан (права - в пределах роли владельца). */

export type TokenScope = 'read' | 'tender' | 'upload' | 'tender_import';

export const TOKEN_SCOPES: readonly {
  readonly value: TokenScope;
  readonly label: string;
  readonly hint: string;
}[] = [
  {
    value: 'read',
    label: 'Только чтение (агенты)',
    hint: 'проекты, документы, разбор, модель, задания и исполнители, база и координационный файл',
  },
  {
    value: 'tender',
    label: 'Расчёты TENDER',
    hint: 'читать выпуски базы, загружать и читать расчёты',
  },
  {
    value: 'upload',
    label: 'Загрузка документов и модели',
    hint: 'новые ревизии и IFC, построение и утверждение модели, правки и задания разбора — всё, что закрыто правом загрузки',
  },
  {
    value: 'tender_import',
    label: 'Создание объекта по тендеру (импорт из дашборда)',
    hint: 'Дашборд «Тендеры» создаёт объект Quantor по тендеру TenderHUB, если его ещё нет. Без области «Загрузка» не работает',
  },
];

const LABELS: Readonly<Record<string, string>> = Object.fromEntries(
  TOKEN_SCOPES.map((scope) => [scope.value, scope.label]),
);

/** Подпись областей токена для списка: известные - по-русски, незнакомые - как есть. */
export const scopesLabel = (scopes: readonly string[]): string =>
  scopes.map((scope) => LABELS[scope] ?? scope).join(', ');
