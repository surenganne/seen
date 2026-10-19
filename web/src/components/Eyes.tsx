import { useEffect, useId, useRef } from "react";
import "./eyes.css";

export type EyesState = "idle" | "alert";

/** The Seen mark (assets/brand/eyes.svg): owl eyes, nearly all iris (amber to Minfy orange), a navy pupil with two
 *  glints and orange feather tufts for brows. idle: glances around with quick saccades and pauses, blinks with lids
 *  (now and then twice). alert: looks straight ahead, lids wide, pupils shrink to pinpoints and the tufts lift.
 *  Colours never change; on dark backgrounds the outline turns light. Reduced motion: a still pose. */
export function Eyes({ state = "idle", size = 32, label, onDark = false }: { state?: EyesState; size?: number; label?: string; onDark?: boolean }) {
  const id = useId().replace(/:/g, "");
  const ref = useRef<SVGSVGElement>(null);
  const alert = useRef(state === "alert");
  alert.current = state === "alert";
  useEffect(() => (ref.current ? watch(ref.current, () => alert.current) : undefined), []);
  const eye = (cx: number, side: "l" | "r") => (
    <g key={side}>
      <circle className="eyes-ring" cx={cx} cy={CY} r="13.2" />
      <g clipPath={`url(#${id}c${side})`}>
        <g clipPath={`url(#${id}l${side})`}>
          <circle cx={cx} cy={CY} r="13" fill={`url(#${id}iris)`} />
          <g className="eyes-look">
            <circle className="eyes-pupil" cx={cx} cy={CY} r={PUPIL} />
            <circle cx={cx + 3} cy={CY - 3.6} r="2.5" fill="#fff" />
            <circle cx={cx - 2.6} cy={CY + 3.4} r="1.1" fill="#fff" />
          </g>
        </g>
      </g>
    </g>
  );
  return (
    <svg
      ref={ref}
      className={`eyes eyes-${state}${onDark ? " eyes-on-dark" : ""}`}
      width={Math.round(size * 1.52)}
      height={size}
      viewBox="0 0 64 42"
      role="img"
      aria-label={label ?? (state === "alert" ? "Seen: needs attention" : "Seen")}
      data-state={state}
    >
      <defs>
        <radialGradient id={`${id}iris`} cx="50%" cy="50%" r="55%">
          <stop offset="0" stopColor="#ffd27a" />
          <stop offset=".45" stopColor="#f59a3e" />
          <stop offset=".85" stopColor="#e85d26" />
          <stop offset="1" stopColor="#9e3a12" />
        </radialGradient>
        {EYES.map(([cx, side]) => (
          <g key={side}>
            <clipPath id={`${id}c${side}`}><circle cx={cx} cy={CY} r="12.4" /></clipPath>
            <clipPath id={`${id}l${side}`}><path className="eyes-lens" data-cx={cx} d={lens(cx, OPEN)} /></clipPath>
          </g>
        ))}
      </defs>
      <path className="eyes-tuft" data-side="-1" d="M7 11 Q11 3.5 21 7.5 Q15 6.8 12.5 9.6 Q10 8.6 7 11 Z" />
      <path className="eyes-tuft" data-side="1" d="M57 11 Q53 3.5 43 7.5 Q49 6.8 51.5 9.6 Q54 8.6 57 11 Z" />
      {EYES.map(([cx, side]) => eye(cx, side))}
    </svg>
  );
}

const CY = 25;
const PUPIL = 6.6;
const OPEN = 0.9; // relaxed lids when calm; alert opens to 1.12
const EYES = [[18, "l"], [46, "r"]] as const;

/** An almond whose height is `open` times the eye: the lids' opening. The eye circle clips its corners. */
export function lens(cx: number, open: number): string {
  const h = 14.2 * open;
  return `M${cx - 16},${CY} Q${cx},${CY - 2 * h} ${cx + 16},${CY} Q${cx},${CY + 2 * h} ${cx - 16},${CY} Z`;
}

/** Blink: lids close in 75 ms, hold 30 ms, open over 170 ms (ease-out). 1 = open, 0 = shut. */
export function lidAt(ms: number): number {
  if (ms < 0 || ms >= 275) return 1;
  if (ms < 75) return 1 - (ms / 75) ** 2;
  if (ms < 105) return 0;
  return 1 - (1 - (ms - 105) / 170) ** 3;
}

type Pose = { px: number; py: number; open: number; brow: number; alert: number };

function draw(svg: SVGSVGElement, p: Pose) {
  svg.querySelectorAll<SVGPathElement>(".eyes-lens").forEach((e) => e.setAttribute("d", lens(Number(e.dataset.cx), p.open)));
  svg.querySelectorAll(".eyes-look").forEach((e) => e.setAttribute("transform", `translate(${(p.px * 3.8).toFixed(2)} ${(p.py * 3.2).toFixed(2)})`));
  svg.querySelectorAll(".eyes-pupil").forEach((e) => e.setAttribute("r", (PUPIL - p.alert * 3.6).toFixed(2)));
  svg.querySelectorAll<SVGPathElement>(".eyes-tuft").forEach((e) => {
    const d = Number(e.dataset.side);
    e.setAttribute("transform", `translate(${(-d * p.alert * 1.2).toFixed(2)} ${(-p.brow * 2 - p.alert * 2.4).toFixed(2)}) rotate(${(d * p.alert * 12).toFixed(2)} ${d < 0 ? 14 : 50} 9)`);
  });
}

type Motion = { px: number; py: number; vx: number; vy: number; tx: number; ty: number; a: number; va: number; brow: number;
  browT: number; browUntil: number; blinkAt: number; nextLook: number; nextBlink: number };
type Mark = { svg: SVGSVGElement; alert: () => boolean; s: Motion };
const marks = new Set<Mark>();
let frame = 0;
let last = 0;
const rand = (a: number, b: number) => a + Math.random() * (b - a);
const still = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Every mark on the page shares one animation frame loop; each still moves on its own random schedule. */
function watch(svg: SVGSVGElement, alert: () => boolean): () => void {
  const now = typeof performance === "undefined" ? 0 : performance.now();
  const m: Mark = { svg, alert, s: { px: 0, py: 0, vx: 0, vy: 0, tx: 0, ty: 0, a: alert() ? 1 : 0, va: 0, brow: 0, browT: 0,
    browUntil: 0, blinkAt: -1e9, nextLook: now + rand(300, 2400), nextBlink: now + rand(800, 5000) } };
  marks.add(m);
  if (typeof requestAnimationFrame === "function" && !frame) frame = requestAnimationFrame(loop);
  else draw(svg, { px: 0, py: 0, open: m.s.a ? 1.12 : OPEN, brow: 0, alert: m.s.a });
  return () => {
    marks.delete(m);
    if (!marks.size && frame) { cancelAnimationFrame(frame); frame = 0; }
  };
}

function loop(now: number) {
  const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
  last = now;
  const calm = still();
  marks.forEach((m) => step(m, now, dt, calm));
  frame = marks.size ? requestAnimationFrame(loop) : 0;
  if (!frame) last = 0;
}

function step({ svg, alert, s }: Mark, now: number, dt: number, calm: boolean) {
  const on = alert();
  if (calm) {
    draw(svg, { px: 0, py: 0, open: on ? 1.12 : OPEN, brow: 0, alert: on ? 1 : 0 });
    return;
  }
  // alert: a slightly underdamped spring, so the eyes pop open and settle
  const ka = 260, ca = 1.25 * Math.sqrt(ka);
  s.va += ((on ? 1 : 0) - s.a) * ka * dt - s.va * ca * dt;
  s.a += s.va * dt;
  if (on) { s.tx = 0; s.ty = 0; }
  else if (now > s.nextLook) {
    if (Math.random() < 0.3) { s.tx = rand(-0.15, 0.15); s.ty = rand(-0.1, 0.1); } // back to centre
    else { const ang = rand(0, Math.PI * 2), r = Math.sqrt(rand(0.35, 1)); s.tx = Math.cos(ang) * r; s.ty = Math.sin(ang) * r * 0.8; }
    s.nextLook = now + (Math.random() < 0.25 ? rand(2600, 4800) : rand(700, 2200));
    if (s.ty < -0.5 && Math.random() < 0.5) { s.browT = 1; s.browUntil = now + rand(500, 900); } // looking up lifts the tufts
  }
  // gaze: a stiff, critically damped spring reads as a saccade: fast, then still
  const k = 1100, c = 2 * Math.sqrt(k);
  s.vx += (s.tx - s.px) * k * dt - s.vx * c * dt; s.px += s.vx * dt;
  s.vy += (s.ty - s.py) * k * dt - s.vy * c * dt; s.py += s.vy * dt;
  if (now > s.nextBlink) { s.blinkAt = now; s.nextBlink = now + (Math.random() < 0.18 ? 230 : rand(2800, 6500) * (on ? 1.8 : 1)); }
  if (now > s.browUntil) s.browT = 0;
  s.brow += (s.browT - s.brow) * Math.min(1, dt * 12);
  const a = Math.max(0, s.a);
  draw(svg, { px: s.px, py: s.py, open: (OPEN + a * (1.12 - OPEN) + Math.max(0, s.a - 1) * 0.4) * Math.max(0.04, lidAt(now - s.blinkAt)), brow: s.brow, alert: a });
}
