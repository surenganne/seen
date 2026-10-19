import { useId } from "react";
import "./eyes.css";

export type EyesState = "idle" | "alert";

/** The Seen mark (assets/brand/eyes.svg): two round eyes, transparent background.
 *  idle: looks around and blinks. alert: stops, stares straight ahead, iris and rim turn crimson. Reduced motion respected. */
export function Eyes({ state = "idle", size = 32, label, onDark = false }: { state?: EyesState; size?: number; label?: string; onDark?: boolean }) {
  const id = useId().replace(/:/g, "");
  const eye = (cx: number, side: "l" | "r") => (
    <g className="eyes-eye">
      <circle className="eyes-rim" cx={cx} cy="32" r="13.5" />
      <g clipPath={`url(#${id}${side})`}>
        <g className="eyes-look">
          <circle cx={cx} cy="32" r="7.2" fill={`url(#${id}iris)`} className="eyes-iris" />
          <circle cx={cx} cy="32" r="3.4" className="eyes-pupil" />
          <circle cx={cx + 2.6} cy="29.2" r="1.8" className="eyes-glint" />
          <circle cx={cx - 2.4} cy="34.6" r="0.8" className="eyes-glint" />
        </g>
      </g>
    </g>
  );
  return (
    <svg
      className={`eyes eyes-${state}${onDark ? " eyes-on-dark" : ""}`}
      width={size * 1.5}
      height={size * 0.75}
      viewBox="0 16 64 32"
      role="img"
      aria-label={label ?? (state === "alert" ? "Seen: needs attention" : "Seen")}
      data-state={state}
    >
      <defs>
        <radialGradient id={`${id}iris`} cx="40%" cy="35%" r="70%">
          <stop offset="0" className="eyes-iris-hi" />
          <stop offset=".6" className="eyes-iris-mid" />
          <stop offset="1" className="eyes-iris-lo" />
        </radialGradient>
        <clipPath id={`${id}l`}><circle cx="17" cy="32" r="12.2" /></clipPath>
        <clipPath id={`${id}r`}><circle cx="47" cy="32" r="12.2" /></clipPath>
      </defs>
      {eye(17, "l")}
      {eye(47, "r")}
    </svg>
  );
}
