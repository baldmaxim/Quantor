/**
 * Синтетический лист A1 для замера просмотрщика.
 *
 * Эталонный чертёж Stage 2A — частный пакет вне git, и на чистой машине его нет. Замер при
 * этом должен запускаться везде, поэтому рядом с эталоном всегда меряется синтетический лист:
 * тот же формат A1, плотная векторная графика — сетка осей, контуры помещений, штриховка.
 *
 * Генератор детерминированный: один и тот же seed даёт побайтно тот же PDF, и отпечаток
 * файла в отчёте подтверждает, что замеры сделаны на одном и том же листе.
 */

const A1_LANDSCAPE = { width: 2384, height: 1684 };

/** Линейный конгруэнтный генератор: Math.random сделал бы соседние замеры несравнимыми. */
const sequence = (seed) => {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
};

const fixed = (value) => value.toFixed(2);

const contentStream = ({ width, height }, next) => {
  const ops = ['0 0 0 RG'];

  // Сетка осей: длинные тонкие линии через весь лист.
  ops.push('0.25 w');
  for (let x = 40; x < width - 40; x += 48) ops.push(`${x} 40 m ${x} ${height - 40} l`);
  for (let y = 40; y < height - 40; y += 48) ops.push(`40 ${y} m ${width - 40} ${y} l`);
  ops.push('S');

  // Контуры помещений: прямоугольники разной величины.
  ops.push('1.1 w');
  for (let index = 0; index < 1200; index += 1) {
    const x = 60 + next() * (width - 280);
    const y = 60 + next() * (height - 280);
    ops.push(`${fixed(x)} ${fixed(y)} ${fixed(20 + next() * 200)} ${fixed(20 + next() * 200)} re`);
  }
  ops.push('S');

  // Штриховка и мелочь: короткие отрезки, которых на настоящем листе десятки тысяч.
  ops.push('0.35 w');
  for (let index = 0; index < 24000; index += 1) {
    const x = 50 + next() * (width - 100);
    const y = 50 + next() * (height - 100);
    ops.push(
      `${fixed(x)} ${fixed(y)} m ${fixed(x + (next() - 0.5) * 28)} ${fixed(y + (next() - 0.5) * 28)} l`,
    );
  }
  ops.push('S');

  return ops.join('\n');
};

/** Собирает однострочный PDF 1.4 с таблицей перекрёстных ссылок. Возвращает Buffer. */
export const buildSyntheticDrawing = ({ seed = 20260911, size = A1_LANDSCAPE } = {}) => {
  const content = contentStream(size, sequence(seed));
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${size.width} ${size.height}] /Contents 4 0 R /Resources << >> >>`,
    `<< /Length ${Buffer.byteLength(content, 'latin1')} >>\nstream\n${content}\nendstream`,
  ];

  let body = '%PDF-1.4\n';
  const offsets = [];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body, 'latin1'));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });

  const xrefOffset = Buffer.byteLength(body, 'latin1');
  // Каждая строка таблицы — ровно 20 байт вместе с концом строки, иначе читатель PDF
  // вынужден восстанавливать таблицу и замер начинает мерить восстановление.
  const entries = offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`);
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${entries.join('')}`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;

  return Buffer.from(body, 'latin1');
};
