import { useContext, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Volume2, VolumeX } from 'lucide-react';
import { IntroMotionContext } from './Experience';
import { CatBehavior, clamp, type CatPose, type Point, type CatBounds } from './catBehavior';
import { loadCatFrames, loadPickupFrames } from './catSprites';
import { CatGesture } from './catGesture';

const rows: Record<CatPose, number> = { sit: 0, walk: 1, stretch: 2, lick: 3, prepare: 4, pounce: 4, pet: 5, pickup: 0, carried: 0, fall: 0, land: 0, recover: 0, annoyed: 0 };

export function WorkspaceCat() {
  const paused = useContext(IntroMotionContext);
  const ref = useRef<HTMLDivElement>(null);
  const behavior = useRef(new CatBehavior());
  // A hot-reloaded controller must not keep an instance with the old animation states.
  if (!(behavior.current instanceof CatBehavior)) behavior.current = new CatBehavior();
  const canvasRef = useRef<HTMLCanvasElement>(null), frames = useRef<HTMLCanvasElement[]>([]);
  const boundsRef = useRef<CatBounds>({ left: 16, top: 16, right: 16, bottom: 16 });
  const drag = useRef<CatGesture | null>(null);
  const suppressClick = useRef(false), keyboardCarry = useRef(false);
  const [carrying, setCarrying] = useState(false), [annoyed, setAnnoyed] = useState(false);
  const mood = useRef(false);
  const petUntil = useRef(0), hovered = useRef(false), focused = useRef(false);
  const mouse = useRef<Point | null>(null);
  const [petting, setPetting] = useState(false);
  const [sound, setSound] = useState(true);
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  const audio = useRef<AudioContext | null>(null), purr = useRef<AudioBufferSourceNode | null>(null);
  const soundRef = useRef(sound), lastPurr = useRef(-Infinity);
  soundRef.current = sound;

  function stopPurr() { try { purr.current?.stop(); } catch { /* Already stopped. */ } purr.current = null; }
  function purrSound() {
    if (!soundRef.current || performance.now() - lastPurr.current < 700) return;
    try {
      const context = audio.current ?? new AudioContext(); audio.current = context;
      void context.resume().catch(() => {});
      lastPurr.current = performance.now(); stopPurr();
      const duration = .8, buffer = context.createBuffer(1, Math.floor(context.sampleRate * duration), context.sampleRate);
      const data = buffer.getChannelData(0); let brown = 0;
      for (let i = 0; i < data.length; i++) {
        const t = i / context.sampleRate;
        brown = (brown + (Math.random() * 2 - 1) * .025) / 1.025;
        data[i] = brown * 3.5 * (.55 + .45 * Math.sin(t * Math.PI * 2 * 26)) * Math.min(1, t / .06, (duration - t) / .12);
      }
      const source = context.createBufferSource(), filter = context.createBiquadFilter(), gain = context.createGain();
      source.buffer = buffer; filter.type = 'lowpass'; filter.frequency.value = 220; gain.gain.value = .18;
      source.connect(filter); filter.connect(gain); gain.connect(context.destination); purr.current = source;
      source.onended = () => { source.disconnect(); filter.disconnect(); gain.disconnect(); if (purr.current === source) purr.current = null; };
      source.start();
    } catch { /* Visual petting works without Web Audio. */ }
  }
  function pet(duration = 1500) {
    petUntil.current = performance.now() + duration;
    behavior.current.pet(); setPetting(true); purrSound();
  }
  function release() {
    petUntil.current = 0; behavior.current.release(); setPetting(false); stopPurr();
  }
  function pickUp() {
    release(); behavior.current.pickUp(); setCarrying(true); setAnnoyed(false); mood.current = false;
  }
  function endDrag(event?: ReactPointerEvent<HTMLButtonElement>, cancel = false) {
    const current = drag.current;
    drag.current = null;
    // The pointer gesture owns its result; the browser's following click must not
    // pet twice, or forgive the cat immediately after a deliberate drop.
    if (current) suppressClick.current = true;
    if (current?.active || keyboardCarry.current) {
      if (cancel) {
        if (current) behavior.current.position = current.origin;
        behavior.current.change('sit');
      } else behavior.current.drop(boundsRef.current);
      keyboardCarry.current = false; setCarrying(false);
      if (event) { focused.current = false; event.currentTarget.blur(); }
    } else if (current) { if (cancel) release(); else pet(); }
    const button = event?.currentTarget ?? ref.current?.querySelector('.cat-pet');
    if (button && current && button.hasPointerCapture(current.id)) button.releasePointerCapture(current.id);
  }

  useEffect(() => {
    let disposed = false;
    const retries: ReturnType<typeof setTimeout>[] = [];
    const load = (loader: () => Promise<HTMLCanvasElement[]>, offset: number, attempt = 0) => {
      void loader().then(result => {
        if (!disposed) result.forEach((sprite, i) => { frames.current[offset + i] = sprite; });
      }).catch(() => {
        // A new asset can arrive after a live update. Never let it hide the base cat.
        if (!disposed && attempt < 3) retries.push(setTimeout(() => load(loader, offset, attempt + 1), 1000 * (attempt + 1)));
      });
    };
    load(loadCatFrames, 0);
    load(loadPickupFrames, 48);
    return () => { disposed = true; retries.forEach(clearTimeout); };
  }, []);

  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const changed = () => setReduced(media.matches);
    media.addEventListener('change', changed);
    return () => { media.removeEventListener('change', changed); stopPurr(); void audio.current?.close(); audio.current = null; };
  }, []);

  useEffect(() => {
    const cat = ref.current, main = cat?.closest('main');
    if (!cat || !main) return;
    let frame = 0, previous = 0, visible = false, drawn = -1;
    let drawnCanvas: HTMLCanvasElement | null = null;
    const engine = behavior.current;
    const look = (event: PointerEvent) => {
      if (event.pointerType !== 'touch') mouse.current = { x: event.clientX, y: event.clientY };
    };
    const pointerOut = (event: PointerEvent) => { if (!event.relatedTarget) mouse.current = null; };
    function draw(now: number) {
      frame = 0;
      if (!visible || document.hidden) return;
      const dt = previous ? Math.min(.05, (now - previous) / 1000) : 0; previous = now;
      const box = main!.getBoundingClientRect(), width = cat!.offsetWidth, height = cat!.offsetHeight;
      const maxY = Math.max(16, box.height - height - 16);
      const top = clamp(-box.top + 24, 16, maxY);
      const bottom = clamp(innerHeight - box.top - height - 20, top, maxY);
      const bounds = { left: 16, top, right: Math.max(16, box.width - width - 16), bottom };
      boundsRef.current = bounds;
      const cursor = mouse.current ? { x: mouse.current.x - box.left, y: mouse.current.y - box.top } : null;
      const heldPet = drag.current && !drag.current.active;
      if (heldPet) {
        petUntil.current = now + 1500;
        purrSound();
      } else if (engine.pose === 'pet' && now >= petUntil.current) release();
      const resting = paused || reduced;
      if (resting && engine.pose === 'pickup') engine.change('carried');
      if (resting && ['fall', 'land', 'recover'].includes(engine.pose)) engine.change('annoyed');
      engine.step(dt, bounds, cursor, resting || hovered.current || focused.current);
      const reaction = ['pet', 'pickup', 'carried', 'fall', 'land', 'recover', 'annoyed'].includes(engine.pose);
      const pose = resting && !reaction ? 'sit' : engine.pose;
      cat!.dataset.pose = pose;
      if (mood.current !== (engine.annoyedFor > 0)) { mood.current = engine.annoyedFor > 0; setAnnoyed(mood.current); }
      cat!.dataset.moving = String(!resting);
      let cell = 0;
      if (!resting && !['pickup', 'carried', 'fall', 'land', 'recover', 'annoyed'].includes(pose)) {
        if (pose === 'prepare') cell = Math.min(2, Math.floor(engine.elapsed / 1.15 * 3));
        else if (pose === 'pounce') cell = Math.min(6, 3 + Math.floor(engine.elapsed / .65 * 4));
        else cell = Math.floor(engine.elapsed * (pose === 'walk' ? 10 : pose === 'sit' ? 4 : 7)) % 8;
      }
      const jump = pose === 'pounce' ? Math.sin(Math.min(1, engine.elapsed / .65) * Math.PI) * 52 : 0;
      cat!.style.transform = `translate3d(${engine.position.x}px,${engine.position.y - jump}px,0)`;
      const lift = !resting ? pose === 'pickup' ? -12 * Math.min(1, engine.elapsed / .28) : pose === 'carried' ? -12 : pose === 'fall' ? -12 * (1 - Math.min(1, engine.elapsed / .3)) : 0 : 0;
      const sway = pose === 'carried' && !resting ? Math.sin(engine.elapsed * 4) * 4 : 0;
      const squash = pose === 'land' && !resting ? 1 - Math.sin(Math.min(1, engine.elapsed / .55) * Math.PI) * .1 : 1;
      cat!.style.setProperty('--cat-lift', `${lift}px`); cat!.style.setProperty('--cat-sway', `${sway}deg`);
      cat!.style.setProperty('--cat-squash', String(squash));
      cat!.style.setProperty('--cat-facing', String(['sit', 'pet', 'lick', 'pickup', 'carried', 'fall', 'land', 'recover', 'annoyed'].includes(pose) ? 1 : engine.facing));
      let index = rows[pose] * 8 + cell;
      if (pose === 'pickup') index = 48 + Math.min(3, Math.floor(engine.elapsed / .28 * 4));
      else if (pose === 'carried') index = 52 + (resting ? 0 : Math.floor(engine.elapsed * 5) % 4);
      else if (pose === 'fall') index = 56;
      else if (pose === 'land') index = 57 + Math.min(2, Math.floor(engine.elapsed / .55 * 3));
      else if (pose === 'recover') index = 60 + Math.min(3, Math.floor(engine.elapsed / .85 * 4));
      const availableIndex = frames.current[index] ? index : 0;
      // Resolve the live canvas here: a development hot update can replace the node.
      const bodyCanvas = canvasRef.current;
      const spriteContext = bodyCanvas?.getContext('2d');
      if (spriteContext && frames.current[availableIndex]) {
        if (availableIndex !== drawn || bodyCanvas !== drawnCanvas) {
          spriteContext.clearRect(0, 0, 181, 181);
          spriteContext.drawImage(frames.current[availableIndex], 0, 0, 181, 181);
          drawn = availableIndex; drawnCanvas = bodyCanvas;
        }
        cat!.dataset.artReady = 'true';
      }
      const eyes = [[64, 100], [64, 102], [63, 99], [59, 97], [62, 97], [60, 95], [60, 97], [61, 99]][cell];
      cat!.style.setProperty('--eye-left', `${(eyes[0] - 9) / 181 * 100}%`);
      cat!.style.setProperty('--eye-right', `${(eyes[1] - 9) / 181 * 100}%`);
      const center = cat!.getBoundingClientRect();
      const dx = mouse.current ? clamp((mouse.current.x - center.left - width / 2) / 160, -1, 1) : 0;
      const dy = mouse.current ? clamp((mouse.current.y - center.top - 50) / 160, -1, 1) : 0;
      cat!.style.setProperty('--eye-x', `${pose === 'annoyed' ? (dx < 0 ? -2.5 : 2.5) : dx * 2.1}px`);
      cat!.style.setProperty('--eye-y', `${pose === 'annoyed' ? -.5 : dy * 1.3}px`);
      frame = requestAnimationFrame(draw);
    }
    const wake = () => { if (!frame && visible && !document.hidden) { previous = 0; frame = requestAnimationFrame(draw); } };
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) wake(); else { cancelAnimationFrame(frame); frame = 0; endDrag(undefined, true); release(); }
    });
    const visibility = () => { if (document.hidden) { cancelAnimationFrame(frame); frame = 0; endDrag(undefined, true); release(); } else wake(); };
    observer.observe(main);
    window.addEventListener('pointermove', look, { passive: true }); window.addEventListener('pointerout', pointerOut);
    document.addEventListener('visibilitychange', visibility);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('pointermove', look); window.removeEventListener('pointerout', pointerOut); document.removeEventListener('visibilitychange', visibility); };
  }, [paused, reduced]);

  return <div ref={ref} className="workspace-cat" data-pose="sit" data-moving={!paused && !reduced} data-carrying={carrying}
    onPointerEnter={() => { hovered.current = true; }} onPointerLeave={() => { hovered.current = false; }}>
    <button type="button" className="cat-pet" aria-label="Pet Sriren" aria-describedby="cat-hint cat-instructions"
      onPointerDown={e => {
        if (e.button !== 0 || drag.current || keyboardCarry.current) return;
        const box = ref.current!.getBoundingClientRect();
        suppressClick.current = false;
        drag.current = new CatGesture(e.pointerId, { x: e.clientX, y: e.clientY }, { x: e.clientX - box.left, y: e.clientY - box.top }, { ...behavior.current.position }, e.pointerType);
        e.currentTarget.setPointerCapture(e.pointerId);
        pet();
      }}
      onPointerUp={e => { if (drag.current?.id === e.pointerId) endDrag(e); }}
      onPointerCancel={e => { if (drag.current?.id === e.pointerId) endDrag(e, true); }}
      onLostPointerCapture={e => { if (drag.current?.id === e.pointerId) endDrag(e, true); }}
      onPointerEnter={() => { hovered.current = true; if (['sit', 'walk', 'stretch', 'lick', 'prepare', 'pounce'].includes(behavior.current.pose)) behavior.current.change('sit'); }}
      onPointerMove={e => {
        const current = drag.current;
        if (current && current.id === e.pointerId) {
          const gesture = current.move(e.pointerId, { x: e.clientX, y: e.clientY });
          if (gesture === 'pickup') pickUp();
          else if (gesture === 'pet') petUntil.current = performance.now() + 1500;
          if (current.active) {
            const box = ref.current!.closest('main')!.getBoundingClientRect();
            behavior.current.carryTo({ x: e.clientX - box.left - current.offset.x, y: e.clientY - box.top - current.offset.y }, boundsRef.current);
          }
          return;
        }
      }}
      onKeyDown={e => {
        if (e.key.toLowerCase() === 'p' && !keyboardCarry.current) { e.preventDefault(); suppressClick.current = false; keyboardCarry.current = true; pickUp(); }
        else if (keyboardCarry.current) {
          if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
            e.preventDefault(); const position = behavior.current.position;
            behavior.current.carryTo({ x: position.x + (e.key === 'ArrowLeft' ? -20 : e.key === 'ArrowRight' ? 20 : 0), y: position.y + (e.key === 'ArrowUp' ? -20 : e.key === 'ArrowDown' ? 20 : 0) }, boundsRef.current);
          } else if (['Enter', ' ', 'Escape'].includes(e.key)) { e.preventDefault(); endDrag(undefined, e.key === 'Escape'); }
        }
      }}
      onFocus={() => { focused.current = true; }} onBlur={() => { focused.current = false; if (keyboardCarry.current) endDrag(); }}
      onClick={() => { if (suppressClick.current) { suppressClick.current = false; return; } if (!carrying) pet(); }}>
      <span className="cat-art" aria-hidden="true"><canvas ref={canvasRef} width="181" height="181" className="cat-sprite"/><span className="cat-flush"/><span className="cat-eyes"><i/><i/></span><span className="cat-frown"/></span>
    </button>
    <span className="cat-instructions" id="cat-instructions">Click or hold anywhere on Sriren to pet. Small strokes keep petting; drag farther to pick up. Keyboard: P to pick up, arrow keys to move, Enter to drop, Escape to cancel. Pet to forgive.</span>
    <div className="cat-caption"><span id="cat-hint" role="status" aria-live="polite">{carrying ? 'Put me down…' : petting ? 'Prrr…' : annoyed ? 'Excuse me?' : 'Pet Sriren'}</span><button className="cat-sound" type="button" aria-label={sound ? 'Mute Sriren’s purring' : 'Enable Sriren’s purring'} aria-pressed={sound} onFocus={() => { focused.current = true; }} onBlur={() => { focused.current = false; }} onClick={() => { setSound(!sound); if (sound) stopPurr(); }}>{sound ? <Volume2 size={12}/> : <VolumeX size={12}/>}</button></div>
  </div>;
}
