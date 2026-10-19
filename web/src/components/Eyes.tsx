import { useId } from "react";
import "./eyes.css";

export type EyesState = "idle" | "alert";

/** The Seen mark (assets/brand/eyes.svg), transparent.
 *  idle: looks around and blinks. alert: stops, stares straight ahead, iris turns crimson. Reduced motion respected. */
export function Eyes({ state = "idle", size = 32, label, onDark = false }: { state?: EyesState; size?: number; label?: string; onDark?: boolean }) {
  const id = useId().replace(/:/g, "");
  const eye = (cx: number, side: "l" | "r") => (
    <g className="eyes-eye">
      <path className="eyes-rim" d={`M${cx - 14} 32 Q${cx} 13 ${cx + 14} 32 Q${cx} 51 ${cx - 14} 32Z`} />
      <g clipPath={`url(#${id}${side})`}>
        <g className="eyes-look">
          <circle cx={cx} cy="32" r="6.9" fill={`url(#${id}iris)`} className="eyes-iris" />
          <circle cx={cx} cy="32" r="3.1" className="eyes-pupil" />
          <circle cx={cx + 2.2} cy="29.8" r="1.4" className="eyes-glint" />
        </g>
      </g>
    </g>
  );
  return (
    <svg
      className={`eyes eyes-${state}${onDark ? " eyes-on-dark" : ""}`}
      width={size}
      height={size}
      viewBox="0 6 64 52"
      role="img"
      aria-label={label ?? (state === "alert" ? "Seen: needs attention" : "Seen")}
      data-state={state}
    >
      <defs>
        <radialGradient id={`${id}iris`} cx="45%" cy="40%" r="65%">
          <stop offset="0" className="eyes-iris-hi" />
          <stop offset=".55" className="eyes-iris-mid" />
          <stop offset="1" className="eyes-iris-lo" />
        </radialGradient>
        <clipPath id={`${id}l`}><path d="M4 32 Q18 13 32 32 Q18 51 4 32Z" /></clipPath>
        <clipPath id={`${id}r`}><path d="M32 32 Q46 13 60 32 Q46 51 32 32Z" /></clipPath>
      </defs>
      {eye(18, "l")}
      {eye(46, "r")}
    </svg>
  );
}
