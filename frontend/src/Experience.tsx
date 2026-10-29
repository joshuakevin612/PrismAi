import { createContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUpRight, Moon, Pause, Play, Sun } from 'lucide-react';
import gsap from 'gsap';
import { useGSAP } from '@gsap/react';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { LiquidReveal } from './LiquidReveal';

gsap.registerPlugin(useGSAP, ScrollTrigger);
export const IntroMotionContext = createContext(false);

export function PrismMark() {
  return <svg width="28" height="30" viewBox="0 0 28 30" fill="none" aria-hidden="true">
    <path d="M14 3 26 26H2L14 3Z M14 11 22 26" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
  </svg>;
}

export function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('prism-theme', theme); } catch { /* Storage is optional. */ }
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'light' ? '#ffffff' : '#080808');
  }, [theme]);
  return <button className="theme-toggle" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
    {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}<span>{theme === 'dark' ? 'Light' : 'Dark'}</span>
  </button>;
}

/** Enter a new surface once; polling never retriggers the animation. */
export function Surface({ children, className = '' }: { children: ReactNode; className?: string }) {
  const scope = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (document.activeElement?.matches(':focus-visible')) return;
    gsap.from(scope.current, { opacity: 0, y: 8, duration: .22, ease: 'power3.out', clearProps: 'all' });
  }, { scope });
  return <div ref={scope} className={className}>{children}</div>;
}

/** Typography leads the introduction; native scroll drives its second movement. */
export function Intro({ children }: { children: ReactNode }) {
  const scope = useRef<HTMLDivElement>(null);
  const introduced = useRef(false);
  const [paused, setPaused] = useState(false);
  useGSAP(() => {
    const media = gsap.matchMedia();
    let disposed = false;
    const ownedTriggers: ScrollTrigger[] = [];
    media.add('(prefers-reduced-motion: no-preference)', () => {
      if (paused) return;
      if (!introduced.current) {
        introduced.current = true;
        gsap.timeline({ defaults: { ease: 'expo.out' } })
          .from('.hero-letter', { yPercent: 115, rotation: 4, duration: .95, stagger: .055 })
          .from('.hero-notes', { opacity: 0, y: 8, duration: .35 }, .55);
      }
      const heroScroll = gsap.timeline({
        defaults: { ease: 'none' },
        scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: .7, invalidateOnRefresh: true },
      })
        .to('.hero-wordmark', { yPercent: -18, scale: .92 }, 0)
        .to('.letter-mask', { yPercent: i => i % 2 ? -12 : 6, rotation: i => i % 2 ? -1.25 : 1.25 }, 0)
        .to('.hero-notes', { opacity: 0, y: -24 }, 0);
      const statementScroll = gsap.fromTo('.statement-word', { opacity: .2 }, {
        opacity: 1, stagger: .12, ease: 'none',
        scrollTrigger: { trigger: '.statement', start: 'top 80%', end: 'top 28%', scrub: .6 },
      });
      const workspaceScroll = gsap.fromTo('.workspace-reveal', { clipPath: 'inset(0 3% 0 3% round 24px)' }, {
        clipPath: 'inset(0 0% 0 0% round 0px)', ease: 'none',
        scrollTrigger: { trigger: '.workspace-reveal', start: 'top 94%', end: 'top 35%', scrub: .65, invalidateOnRefresh: true },
      });
      const explanationScroll = gsap.fromTo('.statement-bottom', { opacity: .35, y: 32 }, {
        opacity: 1, y: 0, ease: 'none',
        scrollTrigger: { trigger: '.statement-bottom', start: 'top 94%', end: 'top 66%', scrub: .65 },
      });
      const arrivalScroll = gsap.timeline({
        defaults: { ease: 'none' },
        scrollTrigger: { trigger: '.workspace-reveal', start: 'top 90%', end: 'top 22%', scrub: .7 },
      })
        .fromTo('.welcome', { y: 28, opacity: .5 }, { y: 0, opacity: 1, duration: .65 })
        .fromTo('.composer', { y: 18, opacity: .65 }, { y: 0, opacity: 1, duration: .6 }, .2);
      [heroScroll, statementScroll, workspaceScroll, explanationScroll, arrivalScroll].forEach(animation => {
        if (animation.scrollTrigger) ownedTriggers.push(animation.scrollTrigger);
      });
    });
    let anchorFrame = 0;
    const settleAnchor = (event: MouseEvent) => {
      if (!(event.target instanceof Element) || !event.target.closest('a[href^="#"]')) return;
      cancelAnimationFrame(anchorFrame);
      anchorFrame = requestAnimationFrame(() => {
        ScrollTrigger.update();
        ownedTriggers.forEach(trigger => trigger.getTween()?.progress(1));
      });
    };
    const root = scope.current;
    root?.addEventListener('click', settleAnchor);
    void document.fonts.ready.then(() => { if (!disposed) ScrollTrigger.refresh(); });
    return () => { disposed = true; cancelAnimationFrame(anchorFrame); root?.removeEventListener('click', settleAnchor); media.revert(); };
  }, { scope, dependencies: [paused], revertOnUpdate: true });
  return <IntroMotionContext.Provider value={paused}><div className="intro" data-motion={paused ? 'paused' : 'full'} ref={scope} id="top" tabIndex={-1}><a className="skip-link" href="#workspace">Skip to workspace</a>
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-stage">
        <LiquidReveal paused={paused}/>
        <header className="hero-header">
          <p>Find the cause.<br/>Decide what happens next.</p>
          <nav aria-label="Primary"><a href="#approach">The approach</a><a className="hero-cta" href="#workspace">Open workspace<ArrowUpRight size={16}/></a></nav>
        </header>
        <h1 className="hero-wordmark" id="hero-title" aria-label="Prism">
          {'PRISM'.split('').map((letter,i)=><span className="letter-mask" aria-hidden="true" key={i}><span className="hero-letter">{letter}</span></span>)}
        </h1>
        <div className="hero-notes">
          <p>A developer assistant.<br/>With you in control.</p>
          <a className="scroll-cue" href="#approach"><ArrowDown size={18}/><span>Scroll to see clearly</span></a>
          <button className="motion-control" onClick={()=>setPaused(!paused)} aria-pressed={paused}>{paused?<Play size={13}/>:<Pause size={13}/>}<span>{paused?'Resume motion':'Pause motion'}</span></button>
        </div>
      </div>
    </section>
    <section className="statement" id="approach" aria-labelledby="statement-title">
      <div className="statement-top"><span>The approach</span><span>Context / diagnosis / review</span></div>
      <h2 id="statement-title" aria-label="The error is a clue. Context is the difference.">
        <span className="statement-line">{'The error is a clue.'.split(' ').map((word,i)=><span className="statement-word" aria-hidden="true" key={i}>{word} </span>)}</span>
        <span className="statement-line">{'Context is the difference.'.split(' ').map((word,i)=><span className="statement-word" aria-hidden="true" key={i}>{word} </span>)}</span>
      </h2>
      <div className="statement-bottom"><p>Prism brings the relevant context together, explains the issue, and proposes changes for your review.</p><a href="#workspace">Start an investigation<ArrowUpRight size={20}/></a></div>
    </section>
    {children}
  </div></IntroMotionContext.Provider>;
}
