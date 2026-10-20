import { Activity, Bot, ChevronRight, FileClock, FolderGit2, History, LayoutDashboard, ListChecks, Monitor, Moon, Settings as Cog, ShieldCheck, ShieldAlert, Sun } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { useProjects, useVerify } from "../api/hooks";
import { useRange, withRange } from "../lib/nav";
import { Eyes } from "./Eyes";
import { Loading } from "./ui";

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
      /* private mode: the theme still applies for this visit */
    }
  }, [theme]);
  return [theme, setTheme];
}

const SECTIONS = [
  ["", "Overview", LayoutDashboard],
  ["changes", "Changes", ListChecks],
  ["sessions", "Sessions", Activity],
  ["timeline", "Timeline", History],
  ["skills", "Skills", Bot],
  ["audit", "Audit", FileClock],
] as const;

function useNarrow(query = "(max-width: 860px)"): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia?.(query).matches === true);
  useEffect(() => {
    const m = window.matchMedia?.(query);
    if (!m) return;
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return narrow;
}

const TITLES: Record<string, string> = { "": "Overview", changes: "Changes", sessions: "Sessions", timeline: "Timeline", skills: "Skills", audit: "Audit" };

export function Layout() {
  const { pid, cid } = useParams();
  const { data: projects } = useProjects();
  const { data: verify } = useVerify();
  const [range, setRange] = useRange();
  const [theme, setTheme] = useTheme();
  const nav = useNavigate();
  const loc = useLocation();
  const current = projects?.find((p) => p.id === pid);
  const alert = (current?.alert ?? false) || verify?.ok === false;
  const section = pid ? (loc.pathname.replace(`/p/${pid}`, "").split("/")[1] ?? "") : "";
  const where = pid ? `${cid ? "Change" : TITLES[section] ?? "Overview"} · ${current?.name ?? pid}` : loc.pathname.startsWith("/settings") ? "Settings" : "Projects";
  useEffect(() => { document.title = `${where} · Seen`; }, [where]); // each page names itself for the tab, history and screen readers
  const narrow = useNarrow();  // one project switcher at a time: rail on desktop, top bar on phones

  const links = (
    <>
      <NavLink to={withRange("/projects", range)} end>
        <FolderGit2 aria-hidden="true" />Projects
      </NavLink>
      {pid &&
        SECTIONS.map(([path, label, Icon]) => (
          <NavLink key={path} to={withRange(`/p/${pid}/${path}`, range)} end={path === ""}>
            <Icon aria-hidden="true" />
            {label}
          </NavLink>
        ))}
      <NavLink to={withRange("/settings", range)}>
        <Cog aria-hidden="true" />Settings
      </NavLink>
    </>
  );

  const projectSelect = (
    <>
      <label className={narrow ? "sr-only" : "rail-heading"} htmlFor="project-switcher">Project</label>
      <select
        id="project-switcher"
        className={narrow ? "select" : undefined}
        value={pid ?? ""}
        onChange={(e) => {
          const keep = ["changes", "skills", "audit"].includes(section) ? section : "";
          nav(withRange(`/p/${e.target.value}/${keep}`, range));
        }}
      >
        {!pid && <option value="">Choose a project</option>}
        {projects?.map((p) => <option key={p.id} value={p.id}>{p.name ?? p.id}</option>)}
      </select>
    </>
  );

  return (
    <>
    <a className="skip-link" href="#content">Skip to content</a>
    <div className="shell">
      <aside className="rail">
        <Link to={withRange("/projects", range)} className="brand" aria-label="Seen home">
          <Eyes state={alert ? "alert" : "idle"} size={34} onDark />
          <span className="brand-name">Seen</span>
        </Link>
        {!narrow && <div className="rail-section">{projectSelect}</div>}
        <nav className="nav" aria-label="Main">{links}</nav>
        <div className="rail-foot">
          {verify && (
            <span className="verify" title={verify.anchor_note}>
              {verify.ok ? <ShieldCheck aria-hidden="true" color="var(--good)" /> : <ShieldAlert aria-hidden="true" color="var(--critical)" />}
              {verify.ok ? `Audit chain verified (${verify.count.toLocaleString()})` : "Audit chain broken"}
            </span>
          )}
          <span>Local data only. Prompts and diffs stay on this machine.</span>
        </div>
      </aside>
      <div className="main">
        <nav className="mobile-nav" aria-label="Main (compact)">{links}</nav>
        <header className="topbar">
          <span className="mobile-only"><Eyes state={alert ? "alert" : "idle"} size={26} /></span>
          <div className="crumbs" aria-label="Breadcrumb">
            {pid ? (
              <>
                <Link to={withRange("/projects", range)}>Projects</Link>
                <ChevronRight size={14} aria-hidden="true" />
                {cid ? (
                  <>
                    <Link to={withRange(`/p/${pid}/changes`, range)}>{current?.name ?? pid}</Link>
                    <ChevronRight size={14} aria-hidden="true" />
                    <strong>Change</strong>
                  </>
                ) : (
                  <strong>{current?.name ?? pid} · {TITLES[section] ?? "Overview"}</strong>
                )}
              </>
            ) : (
              <strong>{loc.pathname.startsWith("/settings") ? "Settings" : "Projects"}</strong>
            )}
          </div>
          <span className="spacer" />
          {narrow && projectSelect}
          <div className="seg" role="group" aria-label="Date range">
            {([7, 14, 28] as const).map((r) => (
              <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>{r}d</button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Theme">
            {([["light", Sun], ["system", Monitor], ["dark", Moon]] as const).map(([t, I]) => (
              <button key={t} type="button" aria-pressed={theme === t} onClick={() => setTheme(t)} aria-label={t} title={t === "system" ? "Follow the OS" : `${t} theme`}>
                <I aria-hidden="true" />
              </button>
            ))}
          </div>
        </header>
        <main id="content" tabIndex={-1} className="content">
          <Suspense fallback={<div className="page"><Loading what="Loading page" /></div>}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
    </>
  );
}
