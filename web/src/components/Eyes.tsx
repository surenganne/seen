import "./eyes.css";

export type EyesState = "idle" | "alert";

/** The Seen mark, built from assets/brand/eyes.svg.
 *  idle: looks around and blinks. alert: stops, stares straight ahead, iris tinted. Respects reduced motion. */
export function Eyes({ state = "idle", size = 36, label }: { state?: EyesState; size?: number; label?: string }) {
  return (
    <svg
      className={`eyes eyes-${state}`}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={label ?? (state === "alert" ? "Seen: needs attention" : "Seen")}
      data-state={state}
    >
      <rect width="64" height="64" rx="14" className="eyes-bg" />
      <ellipse cx="21" cy="32" rx="11" ry="12.5" className="eyes-white" />
      <ellipse cx="43" cy="32" rx="11" ry="12.5" className="eyes-white" />
      <g className="eyes-look">
        <circle cx="21" cy="32" r="6" className="eyes-iris" />
        <circle cx="21" cy="32" r="2.8" className="eyes-pupil" />
        <circle cx="43" cy="32" r="6" className="eyes-iris" />
        <circle cx="43" cy="32" r="2.8" className="eyes-pupil" />
        <circle cx="22.6" cy="30.3" r="1.1" className="eyes-glint" />
        <circle cx="44.6" cy="30.3" r="1.1" className="eyes-glint" />
      </g>
      <rect x="9.5" y="19" width="23" height="26" rx="11" className="eyes-lid" />
      <rect x="31.5" y="19" width="23" height="26" rx="11" className="eyes-lid" />
    </svg>
  );
}
