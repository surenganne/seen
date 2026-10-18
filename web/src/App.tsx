import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Audit } from "./pages/Audit";
import { ChangeDetail } from "./pages/ChangeDetail";
import { Changes } from "./pages/Changes";
import { Memory } from "./pages/Memory";
import { Overview } from "./pages/Overview";
import { Projects } from "./pages/Projects";
import { Settings } from "./pages/Settings";
import { Skills } from "./pages/Skills";

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
      { path: "/p/:pid/memory", element: <Memory /> },
      { path: "/p/:pid/skills", element: <Skills /> },
      { path: "/p/:pid/audit", element: <Audit /> },
      { path: "*", element: <Navigate to="/projects" replace /> },
    ],
  },
];

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } });

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <RouterProvider router={createBrowserRouter(routes)} />
    </QueryClientProvider>
  );
}
