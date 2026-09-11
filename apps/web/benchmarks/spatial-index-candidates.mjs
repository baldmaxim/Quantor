/**
 * Микрозамер кандидатов пространственного индекса (промт 04): линейный перебор, своя равномерная
 * сетка трёх размеров, R-дерево rbush и упакованное дерево flatbush.
 *
 * Зависимости в репозиторий не добавляются: сравнение запускается в отдельном каталоге.
 *
 *   mkdir /tmp/index-bench && cd /tmp/index-bench && npm init -y
 *   npm install rbush@4.0.1 flatbush@4.6.2
 *   node <репозиторий>/apps/web/benchmarks/spatial-index-candidates.mjs
 *
 * Сетка здесь — JS-копия GridIndex (lib/viewer/spatial-index.ts): Node не исполняет TypeScript с
 * параметрами-свойствами. Рабочий GridIndex меряет раздел «Пространственный индекс» замера просмотрщика.
 * Память здесь не меряется: разница кучи Node между построениями — шум. Удержанную память рабочей
 * сетки меряет замер просмотрщика со сборкой мусора. Результат — таблица и JSON в stdout, разбор —
 * docs/stage2b/04-spatial-index.md.
 */

import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

// Пакеты ищутся от текущего каталога, а не от файла: в репозитории их нет намеренно.
const local = createRequire(pathToFileURL(`${process.cwd()}/`));
const load = async (name) => (await import(pathToFileURL(local.resolve(name)).href)).default;
const Flatbush = await load('flatbush');
const RBush = await load('rbush');

const seq = (seed) => {
  let s = seed >>> 0;
  return () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 0x100000000;
};

// Смесь промта 02: до 8 % листа, 1–6 вершин.
const fixture = (n) => {
  const next = seq(20260909);
  const VERT = [1, 2, 6, 5];
  return Array.from({ length: n }, (_, i) => {
    const ox = next() * 0.9;
    const oy = next() * 0.9;
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    for (let k = 0; k < VERT[i % 4]; k += 1) {
      const x = ox + next() * 0.08;
      const y = oy + next() * 0.08;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
    return { minX, minY, maxX, maxY };
  });
};

// Кандидаты AI: мелкие рамки 0,1–1,5 % листа, сгустками вокруг «узлов» чертежа.
const candidates = (n) => {
  const next = seq(7);
  const centers = Array.from({ length: 60 }, () => [next(), next()]);
  return Array.from({ length: n }, () => {
    const c = centers[Math.floor(next() * centers.length)];
    const x = Math.min(0.99, Math.max(0, c[0] + (next() - 0.5) * 0.2));
    const y = Math.min(0.99, Math.max(0, c[1] + (next() - 0.5) * 0.2));
    const w = 0.001 * Math.exp(next() * Math.log(15));
    const h = 0.001 * Math.exp(next() * Math.log(15));
    return { minX: x, minY: y, maxX: x + w, maxY: y + h };
  });
};

const intersects = (a, b) =>
  a.maxX >= b.minX && a.minX <= b.maxX && a.maxY >= b.minY && a.minY <= b.maxY;

class Linear {
  constructor(items) {
    this.items = items.slice();
  }
  search(q, out) {
    const it = this.items;
    for (let i = 0; i < it.length; i += 1) if (intersects(it[i], q)) out.push(i);
  }
  update(i, b) {
    this.items[i] = b;
  }
}

class Grid {
  constructor(items, cells) {
    this.n = cells;
    this.buckets = Array.from({ length: cells * cells }, () => []);
    this.entries = new Array(items.length);
    this.stamp = 0;
    items.forEach((b, i) => this.insert(i, b));
  }
  range(b) {
    const n = this.n;
    const c = (v) => Math.min(n - 1, Math.max(0, Math.floor(v * n)));
    return [c(b.minX), c(b.minY), c(b.maxX), c(b.maxY)];
  }
  insert(i, b) {
    const [x0, y0, x1, y1] = this.range(b);
    const e = { i, b, x0, y0, x1, y1, mark: 0 };
    this.entries[i] = e;
    for (let y = y0; y <= y1; y += 1)
      for (let x = x0; x <= x1; x += 1) this.buckets[y * this.n + x].push(e);
  }
  remove(i) {
    const e = this.entries[i];
    for (let y = e.y0; y <= e.y1; y += 1)
      for (let x = e.x0; x <= e.x1; x += 1) {
        const bucket = this.buckets[y * this.n + x];
        const at = bucket.indexOf(e);
        bucket[at] = bucket[bucket.length - 1];
        bucket.pop();
      }
  }
  update(i, b) {
    this.remove(i);
    this.insert(i, b);
  }
  search(q, out) {
    const stamp = (this.stamp += 1);
    const [x0, y0, x1, y1] = this.range(q);
    for (let y = y0; y <= y1; y += 1)
      for (let x = x0; x <= x1; x += 1) {
        const bucket = this.buckets[y * this.n + x];
        for (let k = 0; k < bucket.length; k += 1) {
          const e = bucket[k];
          if (e.mark === stamp) continue;
          e.mark = stamp;
          if (intersects(e.b, q)) out.push(e.i);
        }
      }
  }
}

class RTree {
  constructor(items) {
    this.tree = new RBush();
    this.nodes = items.map((b, i) => ({ ...b, i }));
    this.tree.load(this.nodes);
  }
  search(q, out) {
    for (const node of this.tree.search(q)) out.push(node.i);
  }
  update(i, b) {
    this.tree.remove(this.nodes[i]);
    this.nodes[i] = { ...b, i };
    this.tree.insert(this.nodes[i]);
  }
}

class Packed {
  constructor(items) {
    this.items = items.slice();
    this.build();
  }
  build() {
    this.index = new Flatbush(this.items.length);
    for (const b of this.items) this.index.add(b.minX, b.minY, b.maxX, b.maxY);
    this.index.finish();
  }
  search(q, out) {
    for (const i of this.index.search(q.minX, q.minY, q.maxX, q.maxY)) out.push(i);
  }
  update(i, b) {
    this.items[i] = b;
    this.build();
  }
}

const percentile = (arr, p) => {
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(s.length * p))];
};

const IMPLS = {
  linear: (items) => new Linear(items),
  grid32: (items) => new Grid(items, 32),
  grid64: (items) => new Grid(items, 64),
  grid128: (items) => new Grid(items, 128),
  rbush: (items) => new RTree(items),
  flatbush: (items) => new Packed(items),
};

const run = (label, generator, sizes) => {
  const rows = [];
  for (const n of sizes) {
    const items = generator(n);
    const next = seq(99);
    // Попадание: точка ± 8 px на листе A1 при 266 % (≈ 0,13 % ширины).
    const hits = Array.from({ length: 3000 }, () => {
      const x = next(),
        y = next(),
        t = 0.0013;
      return { minX: x - t, minY: y - t, maxX: x + t, maxY: y + t };
    });
    // Полоса панорамы: 5 % ширины × высота области (22 %).
    const strips = Array.from({ length: 1000 }, () => {
      const x = next() * 0.95,
        y = next() * 0.78;
      return { minX: x, minY: y, maxX: x + 0.05, maxY: y + 0.22 };
    });
    const moves = Array.from({ length: 1000 }, () => {
      const i = Math.floor(next() * n);
      const b = items[i];
      const dx = (next() - 0.5) * 0.02,
        dy = (next() - 0.5) * 0.02;
      return [i, { minX: b.minX + dx, minY: b.minY + dy, maxX: b.maxX + dx, maxY: b.maxY + dy }];
    });

    for (const [name, make] of Object.entries(IMPLS)) {
      // прогрев
      make(items);
      const t0 = performance.now();
      const index = make(items);
      const buildMs = performance.now() - t0;
      const out = [];
      const hitTimes = [];
      let hitCandidates = 0;
      for (const q of hits) {
        out.length = 0;
        const s = performance.now();
        index.search(q, out);
        hitTimes.push(performance.now() - s);
        hitCandidates += out.length;
      }
      const stripTimes = [];
      for (const q of strips) {
        out.length = 0;
        const s = performance.now();
        index.search(q, out);
        stripTimes.push(performance.now() - s);
      }
      const moveTimes = [];
      const moveCount = name === 'flatbush' ? 30 : moves.length;
      for (const [i, b] of moves.slice(0, moveCount)) {
        const s = performance.now();
        index.update(i, b);
        moveTimes.push(performance.now() - s);
      }
      rows.push({
        data: label,
        n,
        impl: name,
        buildMs: +buildMs.toFixed(2),
        hitMedianMs: +percentile(hitTimes, 0.5).toFixed(4),
        hitP95Ms: +percentile(hitTimes, 0.95).toFixed(4),
        stripMedianMs: +percentile(stripTimes, 0.5).toFixed(4),
        stripP95Ms: +percentile(stripTimes, 0.95).toFixed(4),
        updateMedianMs: +percentile(moveTimes, 0.5).toFixed(4),
        updateP95Ms: +percentile(moveTimes, 0.95).toFixed(4),
        avgHitCandidates: +(hitCandidates / hits.length).toFixed(1),
      });
    }
  }
  return rows;
};

const sizes = [1000, 5000, 10000, 25000];
const rows = [...run('смесь промта 02', fixture, sizes), ...run('кандидаты AI', candidates, sizes)];
console.table(rows);
console.log(JSON.stringify(rows));
