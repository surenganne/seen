import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { useProjects, useVerify } from "../api/hooks";
import { useRange, withRange } from "../lib/nav";
import { Eyes } from "./Eyes";

type Theme = "light" | "dark" | "system";

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const t = localStorage.getItem("seen-theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      if (theme === "system") localStorage.removeItem("seen-theme");
      else localStorage.setItem("seen-theme", theme);
    } catch {
      /* private mode: theme still applies for this visit */
    }
  }, [theme]);
  return [theme, setTheme];
}

const SECTIONS = [
  ["overview", "Overview"],
  ["changes", "Changes"],
  ["memory", "Memory"],
  ["skills", "Skills"],
  ["audit", "Audit"],
] as const;

export function Layout() {
  const { pid } = useParams();
  const { data: projects } = useProjects();
  const { data: verify } = useVerify();
  const [range, setRange] = useRange();
  const [theme, setTheme] = useTheme();
  const nav = useNavigate();
  const loc = useLocation();
  const current = projects?.find((p) => p.id === pid);
  const alert = (current?.alert ?? false) || verify?.ok === false;

  const links = (
    <>
      <NavLink to={withRange("/projects", range)} end>
        <span className="num">00</span>Projects
      </NavLink>
      {pid &&
        SECTIONS.map(([path, label], i) => (
          <NavLink key={path} to={withRange(`/p/${pid}/${path === "overview" ? "" : path}`, range)} end={path === "overview"}>
            <span className="num">{String(i + 1).padStart(2, "0")}</span>
            {label}
          </NavLink>
        ))}
      <NavLink to={withRange("/settings", range)}>
        <span className="num">··</span>Settings
      </NavLink>
    </>
  );

  return (
    <div className="shell">
      <aside className="sidebar">
        <NavLink to={withRange("/projects", range)} className="brand" aria-label="Seen home">
          <Eyes state={alert ? "alert" : "idle"} size={40} />
          <div>
            <div className="brand-name">Seen</div>
            <div className="brand-tag">Nothing your agents do goes unseen.</div>
          </div>
        </NavLink>
        <nav className="nav" aria-label="Main">{links}</nav>
        <div className="sidebar-foot">Local data only. Prompts and diffs never leave this machine.</div>
      </aside>
      <div className="main">
        <nav className="mobile-nav" aria-label="Main (compact)">{links}</nav>
        <header className="topbar">
          <span className="mobile-only"><Eyes state={alert ? "alert" : "idle"} size={28} /></span>
          <label className="eyebrow" htmlFor="project-switcher">Project</label>
          <select
            id="project-switcher"
            className="select"
            value={pid ?? ""}
            onChange={(e) => {
              const rest = pid ? loc.pathname.replace(`/p/${pid}`, "").split("/")[1] ?? "" : "";
              const section = ["changes", "memory", "skills", "audit"].includes(rest) ? rest : "";
              nav(withRange(`/p/${e.target.value}/${section}`, range));
            }}
          >
            {!pid && <option value="">Choose a project</option>}
            {projects?.map((p) => (
              <option key={p.id} value={p.id}>{p.name ?? p.id}</option>
            ))}
          </select>
          <div className="seg" role="group" aria-label="Date range">
            {([7, 14, 28] as const).map((r) => (
              <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>{r}d</button>
            ))}
          </div>
          <span className="spacer" />
          <div className="seg" role="group" aria-label="Theme">
            {(["light", "system", "dark"] as const).map((t) => (
              <button key={t} type="button" aria-pressed={theme === t} onClick={() => setTheme(t)}>{t === "system" ? "auto" : t}</button>
            ))}
          </div>
        </header>
        <Outlet />
      </div>
    </div>
  );
}
