import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = ts.transpileModule(readFileSync(new URL('../src/catBehavior.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { CatBehavior } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const bounds = { left: 16, top: 16, right: 640, bottom: 400 };

test('roaming visits sitting, walking, stretching and grooming and stays in bounds', () => {
  let seed = 42;
  const random = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
  const cat = new CatBehavior(random), poses = new Set();
  for (let i = 0; i < 20000; i++) {
    cat.step(.05, bounds, null); poses.add(cat.pose);
    assert.ok(cat.position.x >= bounds.left && cat.position.x <= bounds.right);
    assert.ok(cat.position.y >= bounds.top && cat.position.y <= bounds.bottom);
    assert.notEqual(cat.pose, 'pet');
  }
  for (const pose of ['sit', 'walk', 'stretch', 'lick']) assert.ok(poses.has(pose), pose);
});

test('petting interrupts a walk, animates in place, then releases to sitting', () => {
  const cat = new CatBehavior(() => .8);
  cat.step(0, bounds, null); cat.target = { x: 80, y: 80 }; cat.change('walk'); cat.step(.1, bounds, null);
  cat.pet(); const position = { ...cat.position };
  cat.step(.2, bounds, { x: 300, y: 200 });
  assert.equal(cat.pose, 'pet'); assert.deepEqual(cat.position, position); assert.ok(cat.elapsed > 0);
  const elapsed = cat.elapsed; cat.pet(); assert.equal(cat.elapsed, elapsed);
  cat.release(); assert.equal(cat.pose, 'sit');
});

test('hunt locks onto a cursor, prepares, pounces and lands without closing eyes', () => {
  const cat = new CatBehavior(() => .1);
  cat.step(0, bounds, null); cat.huntCooldown = 0;
  cat.position = { x: 200, y: 120 }; cat.elapsed = 4;
  cat.step(.05, bounds, { x: 440, y: 200 }); assert.equal(cat.pose, 'prepare');
  const target = { ...cat.target };
  cat.step(1.2, bounds, { x: 50, y: 50 }); assert.equal(cat.pose, 'pounce');
  cat.step(.7, bounds, { x: 50, y: 50 }); assert.equal(cat.pose, 'sit');
  assert.deepEqual(cat.position, target); assert.ok(cat.huntCooldown > 0);
});

test('pause holds position; resize clamps destinations so walking can finish', () => {
  const cat = new CatBehavior(() => .8); cat.step(0, bounds, null);
  cat.target = { x: 600, y: 350 }; cat.change('walk');
  const before = { ...cat.position }; cat.step(3, bounds, null, true); assert.deepEqual(cat.position, before);
  const small = { left: 16, top: 16, right: 180, bottom: 150 };
  for (let i = 0; i < 300; i++) {
    cat.step(.05, small, null);
    assert.ok(cat.position.x <= small.right && cat.position.y <= small.bottom);
    assert.ok(cat.target.x <= small.right && cat.target.y <= small.bottom);
  }
});

test('pickup, dangling, clumsy fall, recovery and annoyed reaction run in order', () => {
  const cat = new CatBehavior(); cat.step(0, bounds, null); cat.change('walk');
  cat.pickUp(); assert.equal(cat.pose, 'pickup'); cat.carryTo({ x: 280, y: 180 }, bounds);
  cat.step(2, bounds, null); assert.equal(cat.pose, 'carried'); assert.deepEqual(cat.position, { x: 280, y: 180 });
  cat.carryTo({ x: -100, y: 900 }, bounds); assert.deepEqual(cat.position, { x: bounds.left, y: bounds.bottom });
  cat.drop(bounds); assert.equal(cat.pose, 'fall');
  cat.step(.31, bounds, null, true); assert.equal(cat.pose, 'land');
  cat.step(.56, bounds, null, true); assert.equal(cat.pose, 'recover');
  cat.step(.86, bounds, null, true); assert.equal(cat.pose, 'annoyed');
  cat.step(5, bounds, null, true); assert.equal(cat.pose, 'annoyed');
  cat.step(5.1, bounds, null, true); assert.equal(cat.pose, 'sit'); assert.equal(cat.annoyedFor, 0);
});

test('petting can interrupt pickup, falling, getting up or anger', () => {
  for (const before of ['pickup', 'carried', 'fall', 'land', 'recover', 'annoyed']) {
    const cat = new CatBehavior(); cat.step(0, bounds, null); cat.pickUp(); cat.drop();
    cat.change(before); cat.annoyedFor = 10;
    assert.equal(cat.pose, before); cat.pet();
    assert.equal(cat.pose, 'pet'); assert.equal(cat.annoyedFor, 0);
    cat.release(); assert.equal(cat.pose, 'sit');
  }
});

test('a fall accelerates downward and stays bounded through viewport changes', () => {
  const cat = new CatBehavior(); cat.step(0, bounds, null); cat.position = { x: 200, y: 100 };
  cat.pickUp(); cat.drop(bounds); cat.step(.1, bounds, null); const firstY = cat.position.y;
  cat.step(.1, bounds, null); assert.ok(cat.position.y - firstY > firstY - 100);
  const small = { ...bounds, bottom: 112 };
  cat.step(.2, small, null); assert.equal(cat.position.y, 112); assert.equal(cat.pose, 'land');
  // Let go even before the pickup animation has finished.
  cat.pickUp(); cat.drop(small); assert.equal(cat.pose, 'fall');
});

const spriteSource = ts.transpileModule(readFileSync(new URL('../src/catSprites.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { isolateSprite } = await import(`data:text/javascript;base64,${Buffer.from(spriteSource).toString('base64')}`);
test('sprite isolation removes adjacent-frame fragments and preserves silhouette antialiasing', () => {
  const width = 12, height = 12, pixels = new Uint8ClampedArray(width * height * 4);
  const alpha = (x, y, a = 255) => { pixels[(y * width + x) * 4 + 3] = a; };
  for (let y = 4; y <= 8; y++) for (let x = 3; x <= 7; x++) alpha(x, y);
  alpha(2, 6, 70); // Real soft edge next to the main silhouette.
  alpha(10, 1); alpha(10, 2); // Disconnected neighboring sprite fragment.
  alpha(0, 7); // No border pixels can smear across animation frames.
  isolateSprite(pixels, width, height);
  assert.equal(pixels[(6 * width + 5) * 4 + 3], 255);
  assert.equal(pixels[(6 * width + 2) * 4 + 3], 70);
  assert.equal(pixels[(1 * width + 10) * 4 + 3], 0);
  assert.equal(pixels[(7 * width) * 4 + 3], 0);
});

const gestureSource = ts.transpileModule(readFileSync(new URL('../src/catGesture.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { CatGesture } = await import(`data:text/javascript;base64,${Buffer.from(gestureSource).toString('base64')}`);
test('a held pet tolerates hand jitter and small strokes before intentional pickup', () => {
  const gesture = new CatGesture(1, { x: 100, y: 100 }, { x: 40, y: 40 }, { x: 60, y: 60 }, 'mouse');
  for (const point of [{ x: 105, y: 103 }, { x: 120, y: 110 }, { x: 90, y: 95 }, { x: 127, y: 100 }]) {
    assert.equal(gesture.move(1, point), 'pet'); assert.equal(gesture.active, false);
  }
  assert.equal(gesture.move(1, { x: 128, y: 100 }), 'pickup');
  assert.equal(gesture.move(1, { x: 100, y: 100 }), 'carry'); // Returning does not accidentally pet away a drop.
});

test('touch is more forgiving and unrelated pointers cannot pick up the cat', () => {
  const gesture = new CatGesture(2, { x: 100, y: 100 }, { x: 40, y: 40 }, { x: 60, y: 60 }, 'touch');
  assert.equal(gesture.move(3, { x: 500, y: 500 }), 'ignore'); assert.equal(gesture.active, false);
  assert.equal(gesture.move(2, { x: 135, y: 100 }), 'pet');
  assert.equal(gesture.move(2, { x: 136, y: 100 }), 'pickup');
});

test('a missing pickup sheet never blocks the base cat and can be retried', async () => {
  const originalImage = globalThis.Image, originalDocument = globalThis.document;
  let pickupAvailable = false;
  globalThis.Image = class {
    naturalWidth = 1448;
    naturalHeight = 1086;
    set src(url) {
      queueMicrotask(() => {
        if (url.includes('pickup') && !pickupAvailable) this.onerror();
        else this.onload();
      });
    }
  };
  globalThis.document = { createElement: () => ({ getContext: () => ({
    drawImage() {}, getImageData: () => ({ data: new Uint8ClampedArray(181 * 181 * 4) }), putImageData() {},
  }) }) };
  try {
    const loader = await import(`data:text/javascript;base64,${Buffer.from(spriteSource).toString('base64')}#loading-test`);
    const base = await loader.loadCatFrames(); assert.equal(base.length, 48);
    await assert.rejects(loader.loadPickupFrames(), /artwork unavailable/);
    assert.equal((await loader.loadCatFrames()).length, 48);
    pickupAvailable = true; assert.equal((await loader.loadPickupFrames()).length, 16);
  } finally { globalThis.Image = originalImage; globalThis.document = originalDocument; }
});
