/**
 * Тема выставляется до первой отрисовки — иначе при загрузке мигает чужая палитра.
 *
 * Скрипт синхронный и в <head> намеренно: любая асинхронность здесь означает кадр
 * с неправильными цветами. `color-scheme` ставится вместе с темой, чтобы системные
 * элементы — полосы прокрутки и поля ввода — не остались светлыми на тёмном фоне.
 */
const THEME_SCRIPT = `
(function () {
  try {
    var saved = localStorage.getItem('quantor-theme');
    var theme = saved === 'dark' || saved === 'light' ? saved : null;
    if (theme) {
      document.documentElement.setAttribute('data-theme', theme);
      document.documentElement.style.colorScheme = theme;
    }
    var dark = theme
      ? theme === 'dark'
      : matchMedia('(prefers-color-scheme: dark)').matches;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', dark ? '#0f1216' : '#f1f4f7');
  } catch (error) {
    /* приватный режим — остаётся системная тема */
  }
})();
`;

export const ThemeScript = () => (
  <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} suppressHydrationWarning />
);
