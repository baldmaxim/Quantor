import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Страж каскада общих стилей.
 *
 * Проверяется исходник, а не отрисовка: в jsdom нет ни слоёв, ни вычисленных
 * стилей, а ошибка, которую этот тест ловит, случилась именно в исходнике —
 * служебные классы лежали вне слоёв, выигрывали у утилит Tailwind и обнуляли
 * отступы, заданные разметкой.
 */

// Рабочий каталог прогона — apps/web (как в bundle.test.ts контура управления).
const css = readFileSync(join(process.cwd(), '../../packages/ui/src/base.css'), 'utf8');

const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '');

/**
 * Заголовки блоков первого уровня: всё, что стоит перед `{` вне любых слоёв.
 *
 * Содержимое `@layer` пропускается целиком — оно и должно там быть. Остальное
 * обязано оказаться в списке разрешённого: токены, кадры анимаций, переходы
 * между страницами и предохранитель уменьшенного движения.
 */
const topLevelBlocks = (): string[] => {
  const blocks: string[] = [];
  let head = '';
  let depth = 0;
  let skipUntil: number | null = null;

  for (const char of withoutComments) {
    if (char === '{') {
      const selector = head.trim().replace(/\s+/g, ' ');
      if (depth === 0) {
        if (selector.startsWith('@layer')) skipUntil = 0;
        else blocks.push(selector);
      }
      depth += 1;
      head = '';
      continue;
    }

    if (char === '}') {
      depth -= 1;
      if (skipUntil !== null && depth <= skipUntil) skipUntil = null;
      head = '';
      continue;
    }

    if (depth === 0 && skipUntil === null) head += char;
  }

  return blocks;
};

describe('base.css', () => {
  it('не оставляет правил классов и тегов вне слоёв', () => {
    // Вне слоёв законно живут только токены, регистрация свойства, кадры
    // анимаций, переходы между страницами и медиазапросы тем. Селектор класса
    // или тега здесь означал бы правило, выигрывающее у любой утилиты.
    const allowed =
      /^(:root|@theme|@property|@keyframes|@media|::view-transition|html, body|html,body)/;

    const offenders = topLevelBlocks().filter((selector) => !allowed.test(selector));

    expect(offenders, 'правила вне слоёв перебивают утилиты Tailwind').toEqual([]);
  });

  it('держит служебные классы в слое components', () => {
    // Именно components, а не utilities: утилиты Tailwind подставляются раньше
    // нашего файла, и внутри одного слоя выиграла бы более поздняя запись.
    for (const name of ['safe-bottom', 'scroll-area', 'press', 'skeleton', 'spinner']) {
      const rule = new RegExp(`^\\s*\\.${name}\\s*\\{`, 'm');
      const match = rule.exec(withoutComments);
      expect(match, `.${name} не объявлен`).not.toBeNull();

      const before = withoutComments.slice(0, match?.index ?? 0);
      const layer = before.lastIndexOf('@layer');
      expect(before.slice(layer, layer + 20), `.${name} вне слоя components`).toContain(
        'components',
      );
    }
  });

  it('складывает вырез экрана, а не подменяет им отступ', () => {
    // env() внутри класса заменял бы padding целиком. Через переменную вырез
    // складывается с отступом разметки: pb-[calc(var(--s-5)+var(--safe-b))].
    const start = /^\s*\.safe-top\s*\{/m.exec(withoutComments)?.index ?? -1;
    expect(start).toBeGreaterThan(-1);

    const block = withoutComments.slice(start, withoutComments.indexOf('}', start + 200));
    expect(block).not.toContain('env(');
    expect(block).toContain('var(--safe-b)');
  });

  it('объявляет одинаковые токены в обеих тёмных палитрах', () => {
    const tokensOf = (start: number): Map<string, string> => {
      const block = css.slice(start, css.indexOf('}', css.indexOf('--shadow-sheet', start)));
      const found = new Map<string, string>();
      for (const [, name, value] of block.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) {
        if (name && value) found.set(name, value.trim());
      }
      return found;
    };

    const system = tokensOf(css.indexOf('@media (prefers-color-scheme: dark)'));
    const chosen = tokensOf(css.indexOf(":root[data-theme='dark']"));

    expect(system.size).toBeGreaterThan(20);

    for (const [name, value] of chosen) {
      // Разойдясь, палитры дают разный вид одной и той же тёмной теме в
      // зависимости от того, выбрана она вручную или взята у системы.
      expect(system.get(name), `токен ${name} разошёлся между тёмными палитрами`).toBe(value);
    }
  });

  it('оставляет предохранитель уменьшенного движения вне слоёв', () => {
    const block = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
    expect(block).toContain('animation-duration: 0.01ms !important');
    // Индикатор иначе замирает в случайном положении: длительность сведена к
    // нулю, но анимация формально продолжается.
    expect(block).toContain('.spinner');
  });

  it('держит предохранители телефона вне слоёв', () => {
    // В слое base они проигрывают утилитам: text-sm на поле ввода возвращал 13px,
    // и Safari снова зумил форму при фокусе. Регрессия была настоящей и поймана
    // мобильным прогоном Playwright — проверяем правило и здесь, на исходнике.
    const index = withoutComments.indexOf('@media (max-width: 767px)');
    expect(index, 'блок мобильных правил не найден').toBeGreaterThan(-1);

    const before = withoutComments.slice(0, index);
    const opened = (before.match(/\{/g) ?? []).length;
    const closed = (before.match(/\}/g) ?? []).length;

    expect(opened - closed, 'мобильные правила оказались внутри слоя').toBe(0);
    expect(withoutComments.slice(index, index + 400)).toContain('font-size: 16px');
  });
});
