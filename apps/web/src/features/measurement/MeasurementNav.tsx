/** Second navigation group for the measurement & learning-loop screens (rendered by Layout). */
import { NavLink } from "react-router-dom";
import { useMT } from "./i18n";

const LINKS = [
  { to: "/quality", key: "nav.quality" },
  { to: "/interventions", key: "nav.interventions" },
  { to: "/pilots/new", key: "nav.pilot_new" },
  { to: "/portfolio/interventions", key: "nav.portfolio" },
] as const;

export function MeasurementNav() {
  const { t2 } = useMT();
  return (
    <div style={{ marginTop: 16 }}>
      <p className="xs muted" id="m-nav-title" style={{ marginBottom: 4 }}>{t2("nav.group")}</p>
      <ul aria-labelledby="m-nav-title" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {LINKS.map((l) => (
          <li key={l.to}>
            <NavLink to={l.to} end={l.to === "/pilots/new"} className={({ isActive }) => (isActive ? "active" : "")}>{t2(l.key)}</NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const MEASUREMENT_ROUTES = [
  "/quality", "/quality/:assessmentId", "/interventions", "/interventions/:id", "/pilots/new", "/pilots/:id", "/pilots/:id/fidelity",
  "/pilots/:id/follow-up", "/portfolio/interventions",
] as const;
