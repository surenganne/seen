import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy } from "react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { ApiError } from "./api/client";
import { Layout } from "./components/Layout";

// Pages load on demand: recharts and the heavier pages stay out of the first download.
const Audit = lazy(() => import("./pages/Audit").then((m) => ({ default: m.Audit })));
const ChangeDetail = lazy(() => import("./pages/ChangeDetail").then((m) => ({ default: m.ChangeDetail })));
const Changes = lazy(() => import("./pages/Changes").then((m) => ({ default: m.Changes })));
const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const Projects = lazy(() => import("./pages/Projects").then((m) => ({ default: m.Projects })));
const Provenance = lazy(() => import("./pages/Provenance").then((m) => ({ default: m.Provenance })));
const Timeline = lazy(() => import("./pages/Timeline").then((m) => ({ default: m.Timeline })));
const Sessions = lazy(() => import("./pages/Sessions").then((m) => ({ default: m.Sessions })));
const Settings = lazy(() => import("./pages/Settings").then((m) => ({ default: m.Settings })));
const Skills = lazy(() => import("./pages/Skills").then((m) => ({ default: m.Skills })));

export const routes = [
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/projects" replace /> },
      { path: "/projects", element: <Projects /> },
      { path: "/settings", element: <Settings /> },
      { path: "/p/:pid", element: <Overview /> },
      { path: "/p/:pid/changes", element: <Changes /> },
      { path: "/p/:pid/changes/:cid", element: <ChangeDetail /> },
      { path: "/p/:pid/sessions", element: <Sessions /> },
      { path: "/p/:pid/timeline", element: <Timeline /> },
      { path: "/p/:pid/skills", element: <Skills /> },
      { path: "/p/:pid/audit", element: <Audit /> },
      { path: "/p/:pid/provenance", element: <Provenance /> },
      { path: "*", element: <Navigate to="/projects" replace /> },
    ],
  },
];

// A 4xx is an answer (not tracked, bad input), not a blip: retry once only for network and 5xx errors.
const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: (n: number, e: Error) => n < 1 && !(e instanceof ApiError && e.status < 500), refetchOnWindowFocus: false } } });

const router = createBrowserRouter(routes); // once, not per render: a re-render must not reset navigation state

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
