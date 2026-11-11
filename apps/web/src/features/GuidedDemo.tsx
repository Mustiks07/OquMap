import { NavLink } from "react-router-dom";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { GUIDE_STEPS, useAppState } from "../state/AppState";
import { Button } from "../ui";

const LINKS: Record<string, string> = {
  overview: "/overview", topic: "/topic", compare: "/compare", plan: "/planner", decision: "/decisions",
  approve: "/decisions", followup: "/decisions",
};

/** 7-step guided demo. Progress is stored locally (survives reloads); limitations stay visible. */
export function GuidedDemo() {
  const { t } = useI18n();
  const { progress, resetProgress } = useAppState();
  const done = GUIDE_STEPS.filter((s) => progress[s]).length;
  return (
    <section aria-labelledby="guide-title" style={{ marginTop: 16, borderTop: "1px solid var(--color-border)", paddingTop: 12 }} data-testid="guide">
      <div className="spread">
        <strong id="guide-title" className="small">{t("guide.title")}</strong>
        <span className="xs muted" aria-label="progress">{done}/{GUIDE_STEPS.length}</span>
      </div>
      <div className="bar-track" style={{ margin: "6px 0 8px" }} role="progressbar" aria-label={t("guide.title")} aria-valuemin={0} aria-valuemax={GUIDE_STEPS.length} aria-valuenow={done}>
        <div className="bar-fill" style={{ width: `${(100 * done) / GUIDE_STEPS.length}%` }} />
      </div>
      <ol style={{ listStyle: "none", padding: 0, margin: 0 }} className="stack xs">
        {GUIDE_STEPS.map((s) => (
          <li key={s}>
            <NavLink to={LINKS[s]} style={{ padding: "2px 4px" }} data-testid={`guide-${s}`} data-done={progress[s] ? "1" : "0"}>
              <span aria-hidden="true" style={{ width: 16, display: "inline-block" }}>{progress[s] ? "✓" : "○"}</span>
              <span className={progress[s] ? "muted" : ""}>{t(`guide.step.${s}` as DictKey)}</span>
              {progress[s] && <span className="sr-only"> — выполнено</span>}
            </NavLink>
          </li>
        ))}
      </ol>
      <p className="xs muted" style={{ marginTop: 8 }}>{t("guide.limits")}</p>
      {done > 0 && <Button size="sm" variant="ghost" onClick={resetProgress}>{t("guide.reset")}</Button>}
    </section>
  );
}
