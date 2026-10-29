/** Keep the character's connected silhouette; discard pieces of neighboring atlas frames.
 * This runs once when the sprite loads. Drawing uses separate canvases, so filtering can
 * never sample a neighboring frame, including while the cat is scaled or carried.
 */
export function isolateSprite(pixels: Uint8ClampedArray, width: number, height: number) {
  const count = width * height, labels = new Int32Array(count), queue = new Int32Array(count);
  let label = 0, largest = 0, largestSize = 0;
  for (let start = 0; start < count; start++) {
    if (labels[start] || pixels[start * 4 + 3] < 96) continue;
    label++; let head = 0, tail = 1; queue[0] = start; labels[start] = label;
    while (head < tail) {
      const i = queue[head++], x = i % width, y = Math.floor(i / width);
      for (const next of [x > 0 ? i - 1 : -1, x < width - 1 ? i + 1 : -1, y > 0 ? i - width : -1, y < height - 1 ? i + width : -1]) {
        if (next >= 0 && !labels[next] && pixels[next * 4 + 3] >= 96) { labels[next] = label; queue[tail++] = next; }
      }
    }
    if (tail > largestSize) { largestSize = tail; largest = label; }
  }
  for (let i = 0; i < count; i++) {
    const x = i % width, y = Math.floor(i / width);
    // A transparent perimeter also prevents edge smearing with GPU interpolation.
    if (x === 0 || x === width - 1 || y === 0 || y === height - 1 || !largest) { pixels[i * 4 + 3] = 0; continue; }
    let keep = labels[i] === largest;
    if (!keep && pixels[i * 4 + 3] < 96) {
      for (let dy = -1; dy <= 1 && !keep; dy++) for (let dx = -1; dx <= 1; dx++) {
        if (labels[i + dy * width + dx] === largest) { keep = true; break; }
      }
    }
    if (!keep) pixels[i * 4 + 3] = 0;
  }
  return pixels;
}

function loadSheet(url: string, columns: number, rows: number) {
  return new Promise<HTMLCanvasElement[]>((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      try {
        const width = image.naturalWidth / columns, height = image.naturalHeight / rows, result: HTMLCanvasElement[] = [];
        for (let row = 0; row < rows; row++) for (let col = 0; col < columns; col++) {
          const canvas = document.createElement('canvas'); canvas.width = 181; canvas.height = 181;
          const context = canvas.getContext('2d', { willReadFrequently: true });
          if (!context) throw new Error('Canvas unavailable');
          context.drawImage(image, col * width, row * height, width, height, 0, 0, 181, 181);
          const data = context.getImageData(0, 0, 181, 181);
          isolateSprite(data.data, 181, 181); context.putImageData(data, 0, 0); result.push(canvas);
        }
        resolve(result);
      } catch (error) { reject(error); }
    };
    image.onerror = () => reject(new Error('Sriren artwork unavailable'));
    image.src = url;
  });
}

let frames: Promise<HTMLCanvasElement[]> | undefined;
export function loadCatFrames() {
  return frames ??= loadSheet('/companion/cat-animation.png', 8, 6)
    .catch(error => { frames = undefined; throw error; });
}

let pickupFrames: Promise<HTMLCanvasElement[]> | undefined;
export function loadPickupFrames() {
  return pickupFrames ??= loadSheet('/companion/sriren-pickup.png', 4, 4)
    .catch(error => { pickupFrames = undefined; throw error; });
}
