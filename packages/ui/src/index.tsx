/**
 * Публичная поверхность пакета.
 *
 * Собрана явным реэкспортом, а не `export *`: набор общего должен быть виден списком,
 * иначе в него незаметно утекает то, что принадлежит одному приложению.
 */

export * from './primitives';
export { ThemeToggle } from './ThemeToggle';
export { ThemeScript } from './ThemeScript';
