import { useEffect, useRef } from 'react';

/** Original animated Prism typography, revealed through a fluid dye mask. */
export function LiquidReveal({ paused }: { paused: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const introduced = useRef(false);
  useEffect(() => {
    const canvas = canvasRef.current, host = canvas?.parentElement;
    const context = canvas?.getContext('2d');
    if (!canvas || !host || !context || paused) return;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)');
    const mask = document.createElement('canvas'), maskContext = mask.getContext('2d');
    if (!maskContext) return;
    let width = 1, height = 1, cols = 144, rows = 80, count = cols * rows;
    let vx = new Float32Array(count), vy = new Float32Array(count), ink = new Float32Array(count);
    let nextX = new Float32Array(count), nextY = new Float32Array(count), nextInk = new Float32Array(count);
    let pressure = new Float32Array(count), nextPressure = new Float32Array(count), divergence = new Float32Array(count), curl = new Float32Array(count);
    let pixels = maskContext.createImageData(cols, rows);
    let frame = 0, visible = false, previous = 0, lastInput = -10000, started = performance.now();
    let demo = !introduced.current, disposed = false;
    let lastPoint: { x: number; y: number; time: number } | null = null;
    const points: { x: number; y: number; time: number }[] = [];

    function stop(clear = false) {
      cancelAnimationFrame(frame); frame = 0; previous = 0;
      if (clear) { context!.clearRect(0, 0, width, height); ink.fill(0); vx.fill(0); vy.fill(0); }
    }
    function wake() {
      if (disposed || frame || !visible || document.hidden || reduce.matches) return;
      frame = requestAnimationFrame(draw);
    }
    function resize() {
      const rect = host!.getBoundingClientRect();
      width = Math.max(rect.width, 1); height = Math.max(rect.height, 1);
      const ratio = Math.min(devicePixelRatio || 1, 1.25, Math.sqrt(1500000 / (width * height)));
      canvas!.width = Math.round(width * ratio); canvas!.height = Math.round(height * ratio);
      context!.setTransform(ratio, 0, 0, ratio, 0, 0);
      cols = width < 600 ? 128 : 192; rows = Math.max(40, Math.round(cols * height / width)); count = cols * rows;
      mask.width = cols; mask.height = rows;
      vx = new Float32Array(count); vy = new Float32Array(count); ink = new Float32Array(count);
      nextX = new Float32Array(count); nextY = new Float32Array(count); nextInk = new Float32Array(count);
      pressure = new Float32Array(count); nextPressure = new Float32Array(count); divergence = new Float32Array(count); curl = new Float32Array(count);
      pixels = maskContext!.createImageData(cols, rows); wake();
    }
    function sample(field: Float32Array, x: number, y: number) {
      x = Math.max(.5, Math.min(cols - 1.5, x)); y = Math.max(.5, Math.min(rows - 1.5, y));
      const ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy, i = iy * cols + ix;
      return (field[i] * (1 - fx) + field[i + 1] * fx) * (1 - fy) + (field[i + cols] * (1 - fx) + field[i + cols + 1] * fx) * fy;
    }
    function addPoint(x: number, y: number, time: number) {
      points.push({ x, y, time });
      if (points.length > 16) points.shift();
      lastInput = time; wake();
    }
    function pointer(event: PointerEvent) {
      if (event.pointerType === 'touch' || (event.target as Element).closest('a,button,input')) return;
      demo = false; introduced.current = true;
      const rect = host!.getBoundingClientRect();
      addPoint((event.clientX - rect.left) / width * cols, (event.clientY - rect.top) / height * rows, performance.now());
    }
    function splat(x: number, y: number, fx: number, fy: number) {
      const radius = cols * .033, square = radius * radius;
      const x0 = Math.max(1, Math.floor(x - radius * 2)), x1 = Math.min(cols - 2, Math.ceil(x + radius * 2));
      const y0 = Math.max(1, Math.floor(y - radius * 2)), y1 = Math.min(rows - 2, Math.ceil(y + radius * 2));
      for (let py = y0; py <= y1; py++) for (let px = x0; px <= x1; px++) {
        const dx = px - x, dy = py - y, weight = Math.exp(-(dx * dx + dy * dy) / square * 1.8), i = py * cols + px;
        ink[i] = Math.min(1.3, ink[i] + weight * .7);
        vx[i] += (fx - dy * 8) * weight; vy[i] += (fy + dx * 8) * weight;
      }
    }
    function simulate(dt: number) {
      while (points.length) {
        const point = points.shift()!;
        const from = lastPoint && point.time - lastPoint.time < 180 ? lastPoint : point;
        const dx = point.x - from.x, dy = point.y - from.y, seconds = Math.max(.016, (point.time - from.time) / 1000);
        const steps = Math.max(1, Math.min(25, Math.ceil(Math.hypot(dx, dy) / 2)));
        const fx = Math.max(-160, Math.min(160, dx / seconds * .3)) / steps;
        const fy = Math.max(-160, Math.min(160, dy / seconds * .3)) / steps;
        for (let j = 1; j <= steps; j++) splat(from.x + dx * j / steps, from.y + dy * j / steps, fx, fy);
        lastPoint = point;
      }
      const damping = Math.exp(-2 * dt);
      for (let y = 1; y < rows - 1; y++) for (let x = 1; x < cols - 1; x++) {
        const i = y * cols + x, bx = x - vx[i] * dt, by = y - vy[i] * dt;
        nextX[i] = sample(vx, bx, by) * damping; nextY[i] = sample(vy, bx, by) * damping;
      }
      [vx, nextX] = [nextX, vx]; [vy, nextY] = [nextY, vy];
      for (let y = 1; y < rows - 1; y++) for (let x = 1; x < cols - 1; x++) {
        const i = y * cols + x;
        curl[i] = (vy[i + 1] - vy[i - 1] - vx[i + cols] + vx[i - cols]) * .5;
      }
      for (let y = 1; y < rows - 1; y++) for (let x = 1; x < cols - 1; x++) {
        const i = y * cols + x, nx = Math.abs(curl[i + 1]) - Math.abs(curl[i - 1]), ny = Math.abs(curl[i + cols]) - Math.abs(curl[i - cols]);
        const n = Math.hypot(nx, ny) + .001;
        vx[i] += ny / n * curl[i] * dt * 2; vy[i] -= nx / n * curl[i] * dt * 2;
        divergence[i] = -.5 * (vx[i + 1] - vx[i - 1] + vy[i + cols] - vy[i - cols]);
      }
      pressure.fill(0);
      for (let iteration = 0; iteration < 8; iteration++) {
        for (let y = 1; y < rows - 1; y++) for (let x = 1; x < cols - 1; x++) {
          const i = y * cols + x;
          nextPressure[i] = (divergence[i] + pressure[i - 1] + pressure[i + 1] + pressure[i - cols] + pressure[i + cols]) * .25;
        }
        [pressure, nextPressure] = [nextPressure, pressure];
      }
      const fade = Math.exp(-2.6 * dt);
      for (let y = 1; y < rows - 1; y++) for (let x = 1; x < cols - 1; x++) {
        const i = y * cols + x;
        vx[i] -= (pressure[i + 1] - pressure[i - 1]) * .5; vy[i] -= (pressure[i + cols] - pressure[i - cols]) * .5;
        nextInk[i] = sample(ink, x - vx[i] * dt, y - vy[i] * dt) * fade;
      }
      [ink, nextInk] = [nextInk, ink];
    }
    function draw(now: number) {
      frame = 0;
      if (disposed || !visible || document.hidden || reduce.matches) return;
      const dt = previous ? Math.min(.033, (now - previous) / 1000) : .016;
      previous = now;
      if (demo && now - started > 450) {
        introduced.current = true;
        const t = Math.min(1, (now - started - 450) / 1150);
        addPoint(cols * (.16 + t * .68), rows * (.48 + Math.sin(t * Math.PI * 2) * .06), now);
        if (t === 1) demo = false;
      }
      if (!demo && now - lastInput > 1800) { stop(true); return; }
      simulate(dt);
      for (let i = 0; i < count; i++) {
        const edge = Math.max(0, Math.min(1, (ink[i] - .08) / .42));
        pixels.data[i * 4 + 3] = Math.round(edge * edge * (3 - 2 * edge) * 255);
      }
      maskContext!.putImageData(pixels, 0, 0);
      context!.clearRect(0, 0, width, height);
      context!.globalCompositeOperation = 'source-over';
      // Authored locally: no third-party footage, external lettering, or media fetch.
      const time = now / 1000;
      context!.fillStyle = '#b3bdcc';
      context!.fillRect(0, 0, width, height);
      context!.save();
      context!.translate(width / 2, height / 2);
      context!.rotate(Math.sin(time * .24) * .045);
      const size = width * .275;
      context!.font = `750 ${size}px "DM Sans", sans-serif`;
      context!.textAlign = 'center'; context!.textBaseline = 'middle';
      const fit = width * .91 / Math.max(1, context!.measureText('PRISM').width);
      context!.scale(fit, 1);
      // Staggered optical echoes move behind a crisp, always-readable wordmark.
      for (let layer = 5; layer >= 0; layer--) {
        context!.fillStyle = layer === 0 ? '#080808' : `rgba(245,248,255,${.12 + layer * .07})`;
        context!.fillText('PRISM', Math.sin(time * .65) * layer * 10, Math.cos(time * .48) * layer * 8);
      }
      context!.restore();
      context!.globalCompositeOperation = 'destination-in';
      context!.imageSmoothingQuality = 'high';
      context!.filter = 'blur(1.5px)';
      context!.drawImage(mask, 0, 0, width, height);
      context!.filter = 'none';
      context!.globalCompositeOperation = 'source-over';
      wake();
    }
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (visible) wake(); else stop(true); }, { threshold: .05 });
    const resizeObserver = new ResizeObserver(resize);
    const visibility = () => { if (document.hidden) stop(true); else wake(); };
    const preference = () => { if (reduce.matches) stop(true); else { demo = false; wake(); } };
    resize(); observer.observe(host); resizeObserver.observe(host);
    host.addEventListener('pointermove', pointer, { passive: true });
    document.addEventListener('visibilitychange', visibility); reduce.addEventListener('change', preference);
    return () => {
      disposed = true; stop(true); observer.disconnect(); resizeObserver.disconnect();
      host.removeEventListener('pointermove', pointer); document.removeEventListener('visibilitychange', visibility);
      reduce.removeEventListener('change', preference);
    };
  }, [paused]);
  return <canvas ref={canvasRef} className="liquid-reveal" aria-hidden="true"/>;
}
