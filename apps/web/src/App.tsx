import { lazy, Suspense, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api/client";
import type { UserOut } from "./api/types";
import { useAppState } from "./state/AppState";
import { Loading } from "./ui";
import { ComparePage } from "./features/ComparePage";
import { DatasetsPage } from "./features/DatasetsPage";
import { DecisionsPage } from "./features/DecisionsPage";
import { ImportPage } from "./features/ImportPage";
import { Layout } from "./features/Layout";
import { LoginPage } from "./features/LoginPage";
import { MaterialsPage } from "./features/MaterialsPage";
import { OverviewPage } from "./features/OverviewPage";
import { PlannerPage } from "./features/PlannerPage";
import { TopicPage } from "./features/TopicPage";
// Measurement & learning-loop screens are loaded on demand (separate chunks; smaller initial bundle).
const lazyNamed = <K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) =>
  lazy(() => load().then((mod) => ({ default: mod[name] })));
const FidelityPage = lazyNamed(() => import("./features/followup/FidelityPage"), "FidelityPage");
const FollowUpPage = lazyNamed(() => import("./features/followup/FollowUpPage"), "FollowUpPage");
const PortfolioPage = lazyNamed(() => import("./features/followup/PortfolioPage"), "PortfolioPage");
const InterventionsPage = lazyNamed(() => import("./features/interventions/InterventionPages"), "InterventionsPage");
const InterventionDetailPage = lazyNamed(() => import("./features/interventions/InterventionPages"), "InterventionDetailPage");
const PilotNewPage = lazyNamed(() => import("./features/interventions/PilotPages"), "PilotNewPage");
const PilotDetailPage = lazyNamed(() => import("./features/interventions/PilotPages"), "PilotDetailPage");
const QualityListPage = lazyNamed(() => import("./features/quality/QualityPages"), "QualityListPage");
const QualityDetailPage = lazyNamed(() => import("./features/quality/QualityPages"), "QualityDetailPage");
const lz = (el: ReactNode) => <Suspense fallback={<Loading />}>{el}</Suspense>;

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, setUser } = useAppState();
  const [checking, setChecking] = useState(!user && !!getToken());
  const nav = useNavigate();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setUser(null);
      nav("/login");
    });
  }, [nav, setUser]);
  useEffect(() => {
    if (user || !getToken()) return;
    api.get<UserOut>("/api/v1/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setChecking(false));
  }, [user, setUser]);
  if (!getToken()) return <Navigate to="/login" replace />;
  if (checking) return <Loading />;
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route path="/" element={<Navigate to="/datasets" replace />} />
        <Route path="/datasets" element={<DatasetsPage />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/topic" element={<TopicPage />} />
        <Route path="/topic/:topicId" element={<TopicPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/planner" element={<PlannerPage />} />
        <Route path="/decisions" element={<DecisionsPage />} />
        <Route path="/decisions/:decisionId" element={<DecisionsPage />} />
        <Route path="/quality" element={lz(<QualityListPage />)} />
        <Route path="/quality/:assessmentId" element={lz(<QualityDetailPage />)} />
        <Route path="/interventions" element={lz(<InterventionsPage />)} />
        <Route path="/interventions/:id" element={lz(<InterventionDetailPage />)} />
        <Route path="/pilots/new" element={lz(<PilotNewPage />)} />
        <Route path="/pilots/:id" element={lz(<PilotDetailPage />)} />
        <Route path="/pilots/:id/fidelity" element={lz(<FidelityPage />)} />
        <Route path="/pilots/:id/follow-up" element={lz(<FollowUpPage />)} />
        <Route path="/portfolio/interventions" element={lz(<PortfolioPage />)} />
      </Route>
      <Route path="*" element={<Navigate to="/datasets" replace />} />
    </Routes>
  );
}
