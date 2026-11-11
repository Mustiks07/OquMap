import { lazy, Suspense, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api/client";
import type { UserOut } from "./api/types";
import { useAppState } from "./state/AppState";
import { Loading } from "./ui";
import { Layout } from "./features/Layout";
import { LoginPage } from "./features/LoginPage";
// Route screens are loaded on demand. Keeping the application shell synchronous makes navigation immediate
// while preventing analytical libraries and large feature modules from inflating the initial bundle.
const lazyNamed = <K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) =>
  lazy(() => load().then((mod) => ({ default: mod[name] })));
const ComparePage = lazyNamed(() => import("./features/ComparePage"), "ComparePage");
const DatasetsPage = lazyNamed(() => import("./features/DatasetsPage"), "DatasetsPage");
const QualityPage = lazyNamed(() => import("./features/DatasetsPage"), "QualityPage");
const UsersPage = lazyNamed(() => import("./features/UsersPage"), "UsersPage");
const DecisionsPage = lazyNamed(() => import("./features/DecisionsPage"), "DecisionsPage");
const ImportPage = lazyNamed(() => import("./features/ImportPage"), "ImportPage");
const MaterialsPage = lazyNamed(() => import("./features/MaterialsPage"), "MaterialsPage");
const OverviewPage = lazyNamed(() => import("./features/OverviewPage"), "OverviewPage");
const PlannerPage = lazyNamed(() => import("./features/PlannerPage"), "PlannerPage");
const TopicPage = lazyNamed(() => import("./features/TopicPage"), "TopicPage");
const GraphPage = lazyNamed(() => import("./features/GraphPage"), "GraphPage");
const CalendarPage = lazyNamed(() => import("./features/CalendarPage"), "CalendarPage");
const QuizPage = lazyNamed(() => import("./features/QuizPage"), "QuizPage");
const SandboxPage = lazyNamed(() => import("./features/SandboxPage"), "SandboxPage");
const TourPage = lazyNamed(() => import("./features/TourPage"), "TourPage");
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
        <Route path="/datasets" element={lz(<DatasetsPage />)} />
        <Route path="/import" element={lz(<ImportPage />)} />
        <Route path="/data-quality" element={lz(<QualityPage />)} />
        <Route path="/users" element={lz(<UsersPage />)} />
        <Route path="/overview" element={lz(<OverviewPage />)} />
        <Route path="/topic" element={lz(<TopicPage />)} />
        <Route path="/topic/:topicId" element={lz(<TopicPage />)} />
        <Route path="/compare" element={lz(<ComparePage />)} />
        <Route path="/materials" element={lz(<MaterialsPage />)} />
        <Route path="/planner" element={lz(<PlannerPage />)} />
        <Route path="/graph" element={lz(<GraphPage />)} />
        <Route path="/graph/:topicId" element={lz(<GraphPage />)} />
        <Route path="/sandbox" element={lz(<SandboxPage />)} />
        <Route path="/calendar" element={lz(<CalendarPage />)} />
        <Route path="/quizzes" element={lz(<QuizPage />)} />
        <Route path="/demo-3min" element={lz(<TourPage />)} />
        <Route path="/decisions" element={lz(<DecisionsPage />)} />
        <Route path="/decisions/:decisionId" element={lz(<DecisionsPage />)} />
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
