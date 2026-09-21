/**
 * Склейка классов.
 *
 * Живёт отдельным модулем, потому что её импортируют все примитивы: оставь её в
 * primitives.tsx — и кнопка, ссылающаяся на неё, замкнула бы зависимость сама на
 * себя (ErrorState рисует кнопку, кнопка берёт cx).
 */
export const cx = (...parts: (string | false | null | undefined)[]): string =>
  parts.filter(Boolean).join(' ');
