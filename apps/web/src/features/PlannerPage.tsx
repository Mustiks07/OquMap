import { useEffect, useState } from "react";
import { usePlanContext, useSolve } from "../api/hooks";
import type { Envelope, PlanResult, PlanScenario, TopicInput } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, ErrorState, Field, Loading, QueryView, StaleBanner, StatusBadge, Tabs } from "../ui";
import { HoursChart } from "../ui/charts";
import { pct } from "../ui/format";
import { NeedDataset } from "./OverviewPage";

type Row = TopicInput & { status?: string | null; score?: number | null; basis?: string; diag?: boolean };
const PRESETS = ["balanced", "minimal_changes", "focus_problem_topics"];

export function PlannerPage() {
  const { t, lang, pick } = useI18n();
  const st = useAppState();
  const ctx = usePlanContext();
  const solve = useSolve();
  const [mode, setMode] = useState<"current" | "illustration">("current");
  const [rows, setRows] = useState<Row[]>([]);
  const [budget, setBudget] = useState(0);
  const [penalty, setPenalty] = useState(0.05);
  const [presets, setPresets] = useState<string[]>(["balanced", "minimal_changes", "focus_problem_topics"]);

  useEffect(() => {
    if (!ctx.data) return;
    if (mode === "current") {
      setRows(ctx.data.topics.map((tp) => ({
        topic_id: tp.topic_id, code: tp.code, title: pick(tp as unknown as Record<string, unknown>, "title"), current_hours: tp.current_hours,
        priority: tp.priority, min_hours: tp.min_hours, max_hours: tp.max_hours, fixed: false, elapsed_hours: tp.elapsed_hours,
        max_change: null, status: tp.topic_status, score: tp.score, basis: tp.priority_basis, diag: tp.recommend_diagnostic,
      })));
      setBudget(ctx.data.budget);
    } else {
      const il = ctx.data.illustration_20h;
      setRows(il.topics.map((x) => ({ topic_id: null, code: x.code, title: x.title, current_hours: x.current_hours, priority: x.priority,
        min_hours: x.min_hours ?? null, max_hours: x.max_hours ?? null, fixed: false, elapsed_hours: 0, max_change: null })));
      setBudget(il.budget);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.data, mode, lang]);

  if (!st.datasetId) return <NeedDataset />;
  const upd = (i: number, patch: Partial<Row>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const intOrNull = (v: string) => (v === "" ? null : Math.max(0, Math.round(Number(v))));
  const run = () =>
    solve.mutate({
      dataset_id: st.datasetId!, plan_id: mode === "current" ? ctx.data?.plan?.id ?? null : null, filters: st.filters,
      topics: rows.map(({ status: _s, score: _sc, basis: _b, diag: _d, ...r }) => r), budget, change_penalty: penalty,
      presets, time_limit_seconds: 5, source_analysis_id: ctx.data?.source_analysis_id ?? null,
    });
  const env = solve.data as Envelope<PlanResult> | undefined;
  const sum = rows.reduce((a, r) => a + r.current_hours, 0);
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t("planner.title")}</h1>
          <p className="muted">{t("planner.lead")}</p>
        </div>
      </div>
      <Tabs label={t("planner.title")} active={mode} onChange={(m) => { setMode(m as "current" | "illustration"); solve.reset(); }}
        tabs={[{ id: "current", label: t("planner.load_current") }, { id: "illustration", label: t("planner.illustration") }]} />
      <QueryView q={ctx}>
        {(c) => (
          <Card title={mode === "current" ? c.plan?.name ?? t("planner.load_current") : t("planner.illustration")}
            actions={mode === "current" && c.plan ? <span className="xs muted">{c.plan.scope} · {c.plan.horizon}</span> : null}>
            <div className="table-wrap">
              <table className="table" data-testid="planner-table">
                <thead>
                  <tr>
                    <th>{t("planner.topic")}</th><th className="num">{t("planner.current")}</th><th className="num">{t("planner.elapsed")}</th>
                    <th className="num">{t("planner.min")}</th><th className="num">{t("planner.max")}</th><th className="num">{t("planner.max_change")}</th>
                    <th>{t("planner.fixed")}</th><th className="num">{t("planner.priority")}</th><th>{t("planner.priority_basis")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={r.code}>
                      <td><strong>{r.code}</strong> <span className="small">{r.title}</span>{r.diag && <div className="xs" style={{ color: "var(--color-warn)" }}>⚠ {t("planner.diagnostic")}</div>}</td>
                      <td className="num"><input aria-label={`${r.code} ${t("planner.current")}`} className="input input-num" type="number" min={0} value={r.current_hours} onChange={(e) => upd(i, { current_hours: intOrNull(e.target.value) ?? 0 })} /></td>
                      <td className="num"><input aria-label={`${r.code} ${t("planner.elapsed")}`} className="input input-num" type="number" min={0} value={r.elapsed_hours ?? 0} onChange={(e) => upd(i, { elapsed_hours: intOrNull(e.target.value) ?? 0 })} /></td>
                      <td className="num"><input aria-label={`${r.code} ${t("planner.min")}`} className="input input-num" type="number" min={0} value={r.min_hours ?? ""} onChange={(e) => upd(i, { min_hours: intOrNull(e.target.value) })} data-testid={`min-${r.code}`} /></td>
                      <td className="num"><input aria-label={`${r.code} ${t("planner.max")}`} className="input input-num" type="number" min={0} value={r.max_hours ?? ""} onChange={(e) => upd(i, { max_hours: intOrNull(e.target.value) })} /></td>
                      <td className="num"><input aria-label={`${r.code} ${t("planner.max_change")}`} className="input input-num" type="number" min={0} value={r.max_change ?? ""} onChange={(e) => upd(i, { max_change: intOrNull(e.target.value) })} /></td>
                      <td><input aria-label={`${r.code} ${t("planner.fixed")}`} type="checkbox" checked={!!r.fixed} onChange={(e) => upd(i, { fixed: e.target.checked })} data-testid={`fixed-${r.code}`} /></td>
                      <td className="num"><input aria-label={`${r.code} ${t("planner.priority")}`} className="input input-num" type="number" min={0} step={0.05} value={r.priority ?? 0} onChange={(e) => upd(i, { priority: Math.max(0, Number(e.target.value)) })} /></td>
                      <td className="xs">{r.basis ? t(`planner.basis.${r.basis}` as DictKey) : "—"}{r.score != null ? ` · ${pct(r.score, lang)}` : ""}{r.status ? <> <StatusBadge status={r.status} /></> : null}</td>
                    </tr>
                  ))}
                  <tr><td><strong>{t("planner.total")}</strong></td><td className="num"><strong>{sum}</strong></td><td colSpan={7} /></tr>
                </tbody>
              </table>
            </div>
            <div className="filters" style={{ marginTop: 12 }}>
              <Field label={t("planner.budget")}>{(id) => <input id={id} className="input" type="number" min={0} value={budget} onChange={(e) => setBudget(Math.max(0, Math.round(Number(e.target.value))))} data-testid="budget" />}</Field>
              <Field label={t("planner.penalty")}>{(id) => <input id={id} className="input" type="number" min={0} step={0.01} value={penalty} onChange={(e) => setPenalty(Math.max(0, Number(e.target.value)))} />}</Field>
              <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
                <legend className="xs muted" style={{ fontWeight: 550 }}>{t("planner.presets")}</legend>
                {PRESETS.map((p) => (
                  <label key={p} className="checkbox" style={{ marginRight: 12 }}>
                    <input type="checkbox" checked={presets.includes(p)} onChange={(e) => setPresets((ps) => (e.target.checked ? [...ps, p] : ps.filter((x) => x !== p)))} />
                    {t(`planner.preset.${p}` as DictKey)}
                  </label>
                ))}
              </fieldset>
              <Button variant="primary" onClick={run} disabled={solve.isPending || presets.length === 0} data-testid="solve">{t("planner.solve")}</Button>
            </div>
            <p className="xs muted" style={{ marginTop: 8 }}>{c.priority_rule} · {t("planner.weights_version")}: {c.weights_version}</p>
          </Card>
        )}
      </QueryView>
      {solve.isPending && <Loading />}
      {solve.isError && <ErrorState error={solve.error} onRetry={run} />}
      {env && (
        <>
          <StaleBanner ctx={env.context} onRecompute={run} />
          <Alert tone="info">{env.result.note_ru}</Alert>
          <div className="grid grid-3" style={{ gridTemplateColumns: `repeat(${Math.min(3, env.result.scenarios.length)}, minmax(0,1fr))` }}>
            {env.result.scenarios.map((sc) => <ScenarioCard key={sc.preset} sc={sc} analysisId={env.context.analysis_id} canUse={mode === "current"} />)}
          </div>
        </>
      )}
    </div>
  );
}

function ScenarioCard({ sc, analysisId, canUse }: { sc: PlanScenario; analysisId: string; canUse: boolean }) {
  const { t, lang } = useI18n();
  const st = useAppState();
  const used = st.draft.planAnalysisId === analysisId && st.draft.planPreset === sc.preset;
  return (
    <Card title={t(`planner.preset.${sc.preset}` as DictKey)}>
      <div className="stack" data-testid={`scenario-${sc.preset}`}>
        <div className="row"><Badge tone={sc.status === "optimal" ? "ok" : sc.status === "feasible" ? "info" : "danger"}>{sc.status}</Badge><span className="small">{lang === "kz" ? sc.status_message_kz : sc.status_message_ru}</span></div>
        {sc.changes && (
          <>
            <HoursChart title={t("planner.result")} labels={[t("planner.before"), t("planner.after")]} rows={sc.changes.map((ch) => ({ code: ch.code, before: ch.before, after: ch.after }))} />
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>{t("planner.topic")}</th><th className="num">{t("planner.before")}</th><th className="num">{t("planner.after")}</th><th className="num">{t("planner.delta")}</th></tr></thead>
                <tbody>
                  {sc.changes.map((ch) => (
                    <tr key={ch.code}><td>{ch.code}</td><td className="num">{ch.before}</td><td className="num"><strong>{ch.after}</strong></td>
                      <td className={`num ${ch.delta > 0 ? "diff-pos" : ch.delta < 0 ? "diff-neg" : ""}`}>{ch.delta > 0 ? `+${ch.delta}` : ch.delta === 0 ? "0" : `−${Math.abs(ch.delta)}`}</td></tr>
                  ))}
                  <tr><td><strong>{t("planner.total")}</strong></td><td className="num">{sc.total_before}</td><td className="num"><strong>{sc.total_after}</strong></td><td /></tr>
                </tbody>
              </table>
            </div>
            {sc.validation?.valid && <Alert tone="ok">{t("planner.valid")}</Alert>}
            <p className="xs muted">{t("planner.objective")}: {String(sc.objective?.formula ?? "")}; λ={String(sc.objective?.change_penalty ?? "")}, r={String(sc.objective?.diminishing_rate ?? "")} · {t("planner.time")}: {String((sc.solver as { wall_time_seconds?: number })?.wall_time_seconds ?? "")} s</p>
            {canUse && (
              <Button variant={used ? "primary" : "default"} aria-pressed={used} data-testid={`use-plan-${sc.preset}`} onClick={() => st.updateDraft({ planAnalysisId: analysisId, planPreset: sc.preset })}>
                {used ? `✓ ${t("compare.used")}` : t("planner.use_in_decision")}
              </Button>
            )}
          </>
        )}
        {sc.status === "infeasible" && sc.conflict && (
          <div className="stack" data-testid="conflict">
            <strong>{t("planner.conflict")}</strong>
            <span className="small">{t("planner.conflict_lead")}</span>
            <ul className="small">
              {(sc.conflict.constraints as { key: string; message_ru: string; message_kz: string }[]).map((c) => <li key={c.key}>{lang === "kz" ? c.message_kz : c.message_ru}</li>)}
            </ul>
            {(sc.conflict.arithmetic as { sum_lower_bounds: number; budget: number } | null) && (
              <Alert tone="danger">{t("planner.arithmetic", { lower: (sc.conflict.arithmetic as { sum_lower_bounds: number }).sum_lower_bounds, budget: (sc.conflict.arithmetic as { budget: number }).budget })}</Alert>
            )}
            <span className="xs muted">verified: {String(sc.conflict.verified)}</span>
          </div>
        )}
        {sc.status === "unknown" && <Alert tone="warn">{sc.status_message_ru}</Alert>}
        {sc.input_errors && <Alert tone="danger">{JSON.stringify(sc.input_errors)}</Alert>}
      </div>
    </Card>
  );
}
