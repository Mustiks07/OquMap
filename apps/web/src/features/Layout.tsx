import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, setToken } from "../api/client";
import { useCurrentDataset } from "../api/hooks";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Badge, Button, SyntheticBadge } from "../ui";
import { dateTime } from "../ui/format";
import { Assistant } from "./Assistant";
import { GuidedDemo } from "./GuidedDemo";
import { MeasurementNav } from "./measurement/MeasurementNav";

const STEPS: { to: string; key: DictKey }[] = [
  { to: "/datasets", key: "nav.datasets" },
  { to: "/overview", key: "nav.overview" },
  { to: "/topic", key: "nav.topic" },
  { to: "/compare", key: "nav.compare" },
  { to: "/materials", key: "nav.materials" },
  { to: "/planner", key: "nav.planner" },
  { to: "/decisions", key: "nav.decision" },
];

export function Layout() {
  const { t, lang, setLang } = useI18n();
  const { user, setUser, assistantOpen, setAssistantOpen } = useAppState();
  const { dataset } = useCurrentDataset();
  const nav = useNavigate();
  const qc = useQueryClient();
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="/datasets" onClick={(e) => { e.preventDefault(); nav("/datasets"); }}>
          OquMap
        </a>
        {dataset ? (
          <span className="row small" style={{ gap: 8, flexWrap: "nowrap", minWidth: 0, flex: "0 1 auto", overflow: "hidden" }} data-testid="dataset-chip">
            <span className="muted">{t("header.dataset")}:</span>
            <strong style={{ maxWidth: 320, minWidth: 40, flexShrink: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={lang === "kz" ? dataset.name_kz : dataset.name_ru}>
              {lang === "kz" ? dataset.name_kz : dataset.name_ru}
            </strong>
            <Badge tone="info" title={dateTime(dataset.version_updated_at, lang)}>
              {t("header.version")} v{dataset.version}
            </Badge>
            {dataset.is_synthetic && <SyntheticBadge />}
          </span>
        ) : null}
        {user?.org_is_ephemeral && user.org_expires_at && (
          <Badge tone="synthetic" title={`${user.org_name} · ${dateTime(user.org_expires_at, lang)}`}>
            {t("header.demo_until", { time: new Date(user.org_expires_at).toLocaleTimeString(lang === "kz" ? "kk-KZ" : "ru-RU", { hour: "2-digit", minute: "2-digit" }) })}
          </Badge>
        )}
        <span className="header-spacer" />
        <div className="row" role="group" aria-label={t("header.lang")} style={{ gap: 4 }}>
          {(["ru", "kz"] as const).map((l) => (
            <Button key={l} size="sm" variant={lang === l ? "primary" : "default"} aria-pressed={lang === l} onClick={() => setLang(l)}>
              {l.toUpperCase()}
            </Button>
          ))}
        </div>
        <Button size="sm" onClick={() => setAssistantOpen(!assistantOpen)} aria-expanded={assistantOpen} disabled={!dataset}>
          {t("nav.assistant")}
        </Button>
        {user && (
          <span className="small muted" title={`${user.display_name} · ${user.org_name}`} style={{ whiteSpace: "nowrap", maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }}>
            {user.display_name}
          </span>
        )}
        <Button size="sm" variant="ghost" onClick={() => { api.post("/api/v1/auth/logout").catch(() => undefined); setToken(null); setUser(null); qc.clear(); nav("/login"); }}>
          {t("header.logout")}
        </Button>
      </header>
      <nav className="app-nav" aria-label="Шаги сценария">
        <ol>
          {STEPS.map((s, i) => (
            <li key={s.to}>
              <NavLink to={s.to} className={({ isActive }) => (isActive ? "active" : "")}>
                <span className="nav-step" aria-hidden="true">{i + 1}</span>
                {t(s.key)}
              </NavLink>
            </li>
          ))}
          <li style={{ marginTop: 8, borderTop: "1px solid var(--color-border)", paddingTop: 8 }}>
            <NavLink to="/demo-3min" className={({ isActive }) => (isActive ? "active" : "")} data-testid="nav-tour">
              <span className="nav-step" aria-hidden="true">▶</span>
              {t("tour.title")}
            </NavLink>
          </li>
          <li>
            <NavLink to="/graph" className={({ isActive }) => (isActive ? "active" : "")} data-testid="nav-graph">
              <span className="nav-step" aria-hidden="true">◇</span>
              {t("graph.title")}
            </NavLink>
          </li>
          <li>
            <NavLink to="/sandbox" className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="nav-step" aria-hidden="true">⇄</span>
              {t("sandbox.title")}
            </NavLink>
          </li>
          <li>
            <NavLink to="/calendar" className={({ isActive }) => (isActive ? "active" : "")} data-testid="nav-calendar">
              <span className="nav-step" aria-hidden="true">▦</span>
              {t("calendar.title")}
            </NavLink>
          </li>
          <li>
            <NavLink to="/quizzes" className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="nav-step" aria-hidden="true">?</span>
              {t("quiz.title")}
            </NavLink>
          </li>
          <li>
            <NavLink to="/data-quality" className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="nav-step" aria-hidden="true">i</span>
              {t("quality.title")}
            </NavLink>
          </li>
          <li>
            <NavLink to="/import" className={({ isActive }) => (isActive ? "active" : "")} data-testid="nav-import">
              <span className="nav-step" aria-hidden="true">↑</span>
              {t("datasets.own_data")}
            </NavLink>
          </li>
          {user?.roles.includes("admin") && !user.org_is_demo && (
            <li>
              <NavLink to="/users" className={({ isActive }) => (isActive ? "active" : "")}>
                <span className="nav-step" aria-hidden="true">⚙</span>
                {t("nav.users")}
              </NavLink>
            </li>
          )}
        </ol>
        {user?.org_is_demo && <GuidedDemo />}
        <MeasurementNav />
        {dataset?.is_synthetic && <p className="xs muted" style={{ marginTop: 16 }}>{t("synthetic.note")}</p>}
      </nav>
      <main className="app-main" id="main">
        <Outlet />
      </main>
      {assistantOpen && dataset && <Assistant onClose={() => setAssistantOpen(false)} />}
    </div>
  );
}
