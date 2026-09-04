/**
 * Ставит data-theme до первой отрисовки, иначе при загрузке мигает чужая тема.
 * Переключатель темы появится вместе с оболочкой портала; пока учитывается системная
 * настройка и сохранённый выбор.
 */
const THEME_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem('quantor-theme');
    if (stored === 'dark' || stored === 'light') {
      document.documentElement.setAttribute('data-theme', stored);
    }
  } catch (error) {
    /* приватный режим — остаётся системная тема */
  }
})();
`;

export const ThemeScript = () => (
  <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} suppressHydrationWarning />
);
