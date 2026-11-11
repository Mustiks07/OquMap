import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api/client";
import type { UserOut } from "./api/types";
import { useAppState } from "./state/AppState";
import { Loading } from "./ui";
import { ComparePage } from "./features/ComparePage";
import { DatasetsPage, QualityPage } from "./features/DatasetsPage";
import { UsersPage } from "./features/UsersPage";
import { DecisionsPage } from "./features/DecisionsPage";
import { ImportPage } from "./features/ImportPage";
import { Layout } from "./features/Layout";
import { LoginPage } from "./features/LoginPage";
import { MaterialsPage } from "./features/MaterialsPage";
import { OverviewPage } from "./features/OverviewPage";
import { PlannerPage } from "./features/PlannerPage";
import { TopicPage } from "./features/TopicPage";

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
        <Route path="/quality" element={<QualityPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/topic" element={<TopicPage />} />
        <Route path="/topic/:topicId" element={<TopicPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/planner" element={<PlannerPage />} />
        <Route path="/decisions" element={<DecisionsPage />} />
        <Route path="/decisions/:decisionId" element={<DecisionsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/datasets" replace />} />
    </Routes>
  );
}
