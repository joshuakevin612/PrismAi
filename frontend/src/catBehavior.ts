export type CatPose = 'sit' | 'walk' | 'stretch' | 'lick' | 'prepare' | 'pounce' | 'pet' | 'pickup' | 'carried' | 'fall' | 'land' | 'recover' | 'annoyed';
export const CAT_SIZE = 96;
export type Point = { x: number; y: number };
export type CatBounds = { left: number; top: number; right: number; bottom: number };
export const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));
const durations: Partial<Record<CatPose, number>> = { sit: 3.5, stretch: 2.8, lick: 3.6, prepare: 1.15, pounce: .65 };

/** Coordinates refer to the cat's top-left, in the main workspace's local space. */
export class CatBehavior {
  pose: CatPose = 'sit';
  position: Point = { x: 0, y: 0 };
  target: Point = { x: 0, y: 0 };
  facing = 1;
  elapsed = 0;
  huntCooldown = 14;
  annoyedFor = 0;
  private launch: Point = { x: 0, y: 0 };
  private fallStart = 0;
  private fallEnd = 0;
  private initialized = false;
  constructor(private random = Math.random) {}
  change(pose: CatPose) { this.pose = pose; this.elapsed = 0; }
  pet() { this.annoyedFor = 0; if (this.pose !== 'pet') this.change('pet'); }
  pickUp() { this.annoyedFor = 0; this.change('pickup'); }
  carryTo(point: Point, bounds: CatBounds) {
    if (this.pose !== 'carried' && this.pose !== 'pickup') return;
    this.position = { x: clamp(point.x, bounds.left, bounds.right), y: clamp(point.y, bounds.top, bounds.bottom) };
  }
  drop(bounds?: CatBounds) {
    if (this.pose !== 'carried' && this.pose !== 'pickup') return;
    this.annoyedFor = 10; this.huntCooldown = 18;
    this.fallStart = this.position.y;
    this.fallEnd = Math.min(this.fallStart + 38, bounds?.bottom ?? this.fallStart + 38);
    this.change('fall');
  }
  release() { if (this.pose === 'pet') this.change('sit'); }
  step(dt: number, bounds: CatBounds, mouse: Point | null, held = false) {
    if (!this.initialized) {
      this.position = { x: bounds.right, y: bounds.top }; this.initialized = true;
    }
    this.position.x = clamp(this.position.x, bounds.left, bounds.right);
    this.position.y = clamp(this.position.y, bounds.top, bounds.bottom);
    this.target.x = clamp(this.target.x, bounds.left, bounds.right);
    this.target.y = clamp(this.target.y, bounds.top, bounds.bottom);
    if (this.pose === 'pet') { this.elapsed += dt; return; }
    if (this.pose === 'pickup') { this.elapsed += dt; if (this.elapsed >= .28) this.change('carried'); return; }
    if (this.pose === 'carried') { this.elapsed += dt; return; }
    // Reactions finish even while hovered: a drop must not freeze the landing or mood.
    if (this.pose === 'fall' || this.pose === 'land' || this.pose === 'recover' || this.pose === 'annoyed') {
      this.elapsed += dt;
      if (this.pose === 'fall') {
        const t = Math.min(1, this.elapsed / .3);
        this.position.y = clamp(this.fallStart + (this.fallEnd - this.fallStart) * t * t, bounds.top, bounds.bottom);
        if (t === 1) this.change('land');
      }
      else if (this.pose === 'land' && this.elapsed >= .55) this.change('recover');
      else if (this.pose === 'recover' && this.elapsed >= .85) this.change('annoyed');
      else if (this.pose === 'annoyed') {
        this.annoyedFor = Math.max(0, this.annoyedFor - dt);
        if (this.annoyedFor === 0) this.change('sit');
      }
      return;
    }
    if (held) return;
    this.elapsed += dt;
    this.huntCooldown = Math.max(0, this.huntCooldown - dt);
    if (this.pose === 'walk') {
      const dx = this.target.x - this.position.x, dy = this.target.y - this.position.y;
      const distance = Math.hypot(dx, dy), travel = 48 * dt;
      if (distance <= travel) { this.position = { ...this.target }; this.change('sit'); }
      else { this.facing = dx < 0 ? -1 : 1; this.position.x += dx / distance * travel; this.position.y += dy / distance * travel; }
      return;
    }
    if (this.pose === 'prepare') {
      if (this.elapsed >= durations.prepare!) { this.launch = { ...this.position }; this.change('pounce'); }
      return;
    }
    if (this.pose === 'pounce') {
      const t = Math.min(1, this.elapsed / durations.pounce!);
      const ease = 1 - (1 - t) ** 2;
      this.position = { x: this.launch.x + (this.target.x - this.launch.x) * ease, y: this.launch.y + (this.target.y - this.launch.y) * ease };
      if (t === 1) this.change('sit');
      return;
    }
    if (this.elapsed < (durations[this.pose] ?? 3)) return;
    const mouseInside = mouse && mouse.x >= bounds.left && mouse.x <= bounds.right + CAT_SIZE && mouse.y >= bounds.top && mouse.y <= bounds.bottom + CAT_SIZE;
    const distance = mouse ? Math.hypot(mouse.x - this.position.x - CAT_SIZE / 2, mouse.y - this.position.y - CAT_SIZE / 2) : 0;
    if (mouseInside && distance > 100 && distance < 520 && this.huntCooldown === 0 && this.random() < .55) {
      // Lock on before crouching: the pointer can escape and the cat can miss.
      this.target = { x: clamp(mouse.x - 80, bounds.left, bounds.right), y: clamp(mouse.y - 70, bounds.top, bounds.bottom) };
      this.facing = this.target.x < this.position.x ? -1 : 1;
      this.huntCooldown = 22 + this.random() * 18;
      this.change('prepare');
    } else if (this.pose === 'sit' && this.random() < .55) {
      this.change(this.random() < .5 ? 'stretch' : 'lick');
    } else {
      this.target = { x: bounds.left + this.random() * (bounds.right - bounds.left), y: bounds.top + this.random() * (bounds.bottom - bounds.top) };
      this.change('walk');
    }
  }
}
