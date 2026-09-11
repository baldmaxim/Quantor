/**
 * Затихание жеста: когда можно делать дорогую работу — pdf.js и перерисовку слоёв целиком.
 *
 * Таймер «180 мс без изменений камеры» ошибается на медленных кадрах: если кадр панорамы сам
 * длится дольше паузы, таймер срабатывает между кадрами посреди жеста. Замер промта 03 поймал
 * это на 266 % при плотности 1,5 — одиннадцать отрисовок pdf.js за 30 секунд панорамы, каждая
 * ещё сильнее тормозила кадры.
 *
 * Поэтому жест затих, только когда выполнены оба условия: с последнего изменения камеры прошло
 * не меньше паузы **и** браузер показал подряд несколько кадров без изменений. Пока камера
 * меняется на каждом кадре, второе условие не наступает, как бы долго кадр ни длился.
 */

/** Кадров подряд без изменений камеры, после которых жест считается затихшим. */
const QUIET_FRAMES = 2;

type FrameScheduler = (callback: () => void) => number;
type FrameCanceller = (handle: number) => void;

const requestFrame: FrameScheduler = (callback) =>
  typeof requestAnimationFrame === 'function'
    ? requestAnimationFrame(callback)
    : (setTimeout(callback, 16) as unknown as number);

const cancelFrame: FrameCanceller = (handle) => {
  if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(handle);
  else clearTimeout(handle);
};

export class GestureSettle {
  private lastChange = 0;
  private quietFrames = 0;
  private frame: number | null = null;

  constructor(
    private readonly delayMs: number,
    private readonly onSettle: () => void,
    private readonly now: () => number = () => performance.now(),
  ) {}

  /** Камера изменилась: отсчёт паузы и тихих кадров начинается заново. */
  change(): void {
    this.lastChange = this.now();
    this.quietFrames = 0;
    if (this.frame === null) this.frame = requestFrame(this.tick);
  }

  dispose(): void {
    if (this.frame !== null) cancelFrame(this.frame);
    this.frame = null;
  }

  private readonly tick = (): void => {
    this.frame = null;
    this.quietFrames += 1;
    if (this.quietFrames >= QUIET_FRAMES && this.now() - this.lastChange >= this.delayMs) {
      this.onSettle();
      return;
    }
    this.frame = requestFrame(this.tick);
  };
}
