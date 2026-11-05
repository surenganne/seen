import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy } from "react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { Layout } from "./components/Layout";

// Pages load on demand: recharts and the heavier pages stay out of the first download.
const Audit = lazy(() => import("./pages/Audit").then((m) => ({ default: m.Audit })));
const ChangeDetail = lazy(() => import("./pages/ChangeDetail").then((m) => ({ default: m.ChangeDetail })));
const Changes = lazy(() => import("./pages/Changes").then((m) => ({ default: m.Changes })));
const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const Projects = lazy(() => import("./pages/Projects").then((m) => ({ default: m.Projects })));
const Team = lazy(() => import("./pages/Team").then((m) => ({ default: m.Team })));
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
      { path: "/team", element: <Team /> },
      { path: "/settings", element: <Settings /> },
      { path: "/p/:pid", element: <Overview /> },
      { path: "/p/:pid/changes", element: <Changes /> },
      { path: "/p/:pid/changes/:cid", element: <ChangeDetail /> },
      { path: "/p/:pid/sessions", element: <Sessions /> },
      { path: "/p/:pid/timeline", element: <Timeline /> },
      { path: "/p/:pid/skills", element: <Skills /> },
      { path: "/p/:pid/audit", element: <Audit /> },
      { path: "*", element: <Navigate to="/projects" replace /> },
    ],
  },
];

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } });

const router = createBrowserRouter(routes); // once, not per render: a re-render must not reset navigation state

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
