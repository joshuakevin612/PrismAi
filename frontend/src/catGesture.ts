import type { Point } from './catBehavior';

/** Separate deliberate carrying from the small movements of a held head-pat. */
export class CatGesture {
  active = false;
  readonly threshold: number;
  constructor(
    readonly id: number,
    readonly start: Point,
    readonly offset: Point,
    readonly origin: Point,
    pointerType: string,
  ) { this.threshold = pointerType === 'touch' ? 36 : 28; }

  move(id: number, point: Point): 'ignore' | 'pet' | 'pickup' | 'carry' {
    if (id !== this.id) return 'ignore';
    if (this.active) return 'carry';
    if (Math.hypot(point.x - this.start.x, point.y - this.start.y) < this.threshold) return 'pet';
    this.active = true;
    return 'pickup';
  }
}
