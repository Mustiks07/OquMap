import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useCurriculum } from "../../api/hooks";
import { useAppState } from "../../state/AppState";
import { Alert, Badge, Button, Card, Field, Select } from "../../ui";
import { dateTime } from "../../ui/format";
import { NeedDataset } from "../OverviewPage";
import { useIntervention, useInterventions, useMAction, usePilot, type PilotCreate, type PilotOut } from "../measurement/api";
import { ActionError, FidelityBadge, KV, LabelText, MQuery, Messages, OutcomeBadge, PilotStatusBadge, useRoles } from "../measurement/components";
import { useMT } from "../measurement/i18n";
import { DesignStudio } from "./DesignStudio";
import { SessionCalendar } from "./SessionCalendar";

const DESIGNS = ["single_group", "matched_comparison", "cluster_randomized", "interrupted_time_series", "stepped_wedge"] as const;
type Arm = "intervention" | "comparison" | "";

export function PilotNewPage() {
  const { t2, pick } = useMT();
  const { datasetId } = useAppState();
  const [sp] = useSearchParams();
  const cur = useCurriculum();
  const ivs = useInterventions({ status: "active", limit: "200" });
  const nav = useNavigate();
  const { canDraft } = useRoles();
  const [ivId, setIvId] = useState(sp.get("intervention") ?? "");
  const iv = useIntervention(ivId || undefined);
  const [version, setVersion] = useState<string>("");
  const [f, setF] = useState({
    title: "", topic_id: "", objective_id: "", primary_outcome_ru: "", design: "single_group" as PilotCreate["design"], assignment_unit: "cohort" as "cohort" | "school",
    baseline_assessment_id: "", outcome_assessment_id: "", start_date: "", end_date: "", follow_up_due: "", owner: "", inclusion_criteria: "",
    exclusion_criteria: "", adjustment: "none" as "none" | "baseline_strata", external_ack: "",
  });
  const [arms, setArms] = useState<Record<string, Arm>>({});
  const create = useMAction<PilotCreate, PilotOut>("POST", () => "/api/v1/pilots");
  if (!datasetId) return <NeedDataset />;
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }));
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const body: PilotCreate = {
      dataset_id: datasetId!, title: f.title, intervention_id: ivId, intervention_version: version ? Number(version) : null,
      topic_id: f.topic_id, objective_id: f.objective_id || null, primary_outcome_ru: f.primary_outcome_ru, design: f.design,
      assignment_unit: f.assignment_unit,
      cohorts: Object.entries(arms).filter(([, a]) => a).map(([cohort_id, arm]) => ({ cohort_id, arm: arm as "intervention" | "comparison", wave: null })),
      baseline_assessment_id: f.baseline_assessment_id || null, outcome_assessment_id: f.outcome_assessment_id || null,
      pre_period_assessment_ids: [], start_date: f.start_date || null, end_date: f.end_date || null, follow_up_due: f.follow_up_due || null,
      owner: f.owner, inclusion_criteria: f.inclusion_criteria, exclusion_criteria: f.exclusion_criteria,
      analysis_plan: { adjustment: f.adjustment, strata_scheme: "pre_three_level", attempt_rule: "first", omitted_policy: "as_incorrect", min_matched_learners: 30, notes: "", primary_estimand: null, external_analysis_acknowledged: f.external_ack === "1" },
    };
    const res = await create.mutateAsync(body);
    nav(`/pilots/${res.id}`);
  }
  const inp = (k: keyof typeof f, label: string, type = "text") => (
    <Field label={label}>{(id) => <input id={id} className="input" type={type} value={f[k]} onChange={(e) => set(k, e.target.value)} />}</Field>
  );
  const assessOpts = [{ value: "", label: "—" }, ...(cur.data?.assessments ?? []).map((a) => ({ value: a.id, label: `${a.code} (${a.form}/${a.scale})` }))];
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t2("pilot.new_title")}</h1>
          <p className="muted">{t2("pilot.new_lead")}</p>
        </div>
      </div>
      {!canDraft && <Alert tone="warn" title={t2("common.forbidden")}>{t2("common.forbidden_hint")}</Alert>}
      <form className="stack" onSubmit={submit} aria-label={t2("pilot.new_title")}>
        <Card title={t2("pilot.intervention")}>
          <div className="grid grid-2">
            <Field label={t2("pilot.intervention")}>
              {(id) => <Select id={id} value={ivId} onChange={(v) => { setIvId(v); setVersion(""); }}
                options={[{ value: "", label: "—" }, ...(ivs.data?.items ?? []).filter((x) => x.reviewed_version).map((x) => ({ value: x.id, label: `${pick(x, "title")} · ${x.code}` }))]} />}
            </Field>
            <Field label={t2("common.version")}>
              {(id) => <Select id={id} value={version} onChange={setVersion}
                options={[{ value: "", label: iv.data?.reviewed_version ? `v${iv.data.reviewed_version} (✓)` : "—" },
                  ...(iv.data?.versions ?? []).map((v) => ({ value: String(v.version), label: `v${v.version} · ${t2(`iv.vstatus.${v.status}`)}` }))]} />}
            </Field>
          </div>
          {iv.data && <p className="small muted">{t2("pilot.dosage", { m: iv.data.current.minutes_per_session, w: iv.data.current.sessions_per_week, n: iv.data.current.duration_weeks, s: iv.data.current.sessions_per_week * iv.data.current.duration_weeks })}</p>}
        </Card>
        <Card title={t2("pilot.title")}>
          <div className="grid grid-2">
            {inp("title", t2("pilot.name"))}
            {inp("owner", t2("pilot.owner"))}
            <Field label={t2("pilot.topic")}>{(id) => <Select id={id} value={f.topic_id} onChange={(v) => { set("topic_id", v); set("objective_id", ""); }}
              options={[{ value: "", label: "—" }, ...(cur.data?.topics ?? []).map((x) => ({ value: x.id, label: `${x.code} ${pick(x, "title")}` }))]} />}</Field>
            <Field label={t2("pilot.objective")}>{(id) => <Select id={id} value={f.objective_id} onChange={(v) => set("objective_id", v)}
              options={[{ value: "", label: "—" }, ...(cur.data?.objectives ?? []).filter((o) => o.topic_id === f.topic_id).map((x) => ({ value: x.id, label: `${x.code} ${pick(x, "text")}` }))]} />}</Field>
          </div>
          {inp("primary_outcome_ru", t2("pilot.outcome"))}
        </Card>
        <Card title={t2("pilot.design")}>
          <div className="grid grid-3">
            <Field label={t2("pilot.design")}>{(id) => <Select id={id} value={f.design} onChange={(v) => set("design", v)}
              options={DESIGNS.map((d) => ({ value: d, label: t2(`pilot.design.${d}`) }))} />}</Field>
            <Field label={t2("pilot.unit")}>{(id) => <Select id={id} value={f.assignment_unit} onChange={(v) => set("assignment_unit", v)}
              options={[{ value: "cohort", label: t2("pilot.unit.cohort") }, { value: "school", label: t2("pilot.unit.school") }]} />}</Field>
            <Field label={t2("pilot.adjustment")}>{(id) => <Select id={id} value={f.adjustment} onChange={(v) => set("adjustment", v)}
              options={[{ value: "none", label: t2("pilot.adjustment.none") }, { value: "baseline_strata", label: t2("pilot.adjustment.baseline_strata") }]} />}</Field>
          </div>
          {(f.design === "interrupted_time_series" || f.design === "stepped_wedge") && (
            <Alert tone="warn" role="note">
              {t2("pilot.analysis_mode.protocol_only_external_analysis")}
              <label className="row small" style={{ gap: 6, marginTop: 6 }}>
                <input type="checkbox" checked={f.external_ack === "1"} onChange={(e) => set("external_ack", e.target.checked ? "1" : "")} /> {t2("pilot.ack_external")}
              </label>
            </Alert>
          )}
          <div className="table-wrap" style={{ maxHeight: 320, overflowY: "auto" }}>
            <table className="table">
              <caption className="sr-only">{t2("pilot.cohorts")}</caption>
              <thead><tr><th scope="col">{t2("pilot.cohorts")}</th><th scope="col">{t2("pilot.arm")}</th></tr></thead>
              <tbody>
                {(cur.data?.cohorts ?? []).map((c) => (
                  <tr key={c.id}>
                    <td className="mono">{c.code}</td>
                    <td>
                      <Select ariaLabel={`${t2("pilot.arm")} ${c.code}`} value={arms[c.id] ?? ""} onChange={(v) => setArms((a) => ({ ...a, [c.id]: v as Arm }))}
                        options={[{ value: "", label: t2("pilot.arm.none") }, { value: "intervention", label: t2("pilot.arm.intervention") }, { value: "comparison", label: t2("pilot.arm.comparison") }]} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <DesignStudio datasetId={datasetId} assignmentUnit={f.assignment_unit}
          cohortIds={Object.entries(arms).filter(([, a]) => a).map(([c]) => c)} onUseDesign={(d) => set("design", d)} />
        <Card title={t2("pilot.baseline")}>
          <div className="grid grid-2">
            <Field label={t2("pilot.baseline")}>{(id) => <Select id={id} value={f.baseline_assessment_id} onChange={(v) => set("baseline_assessment_id", v)} options={assessOpts} />}</Field>
            <Field label={t2("pilot.outcome_assessment")}>{(id) => <Select id={id} value={f.outcome_assessment_id} onChange={(v) => set("outcome_assessment_id", v)} options={assessOpts} />}</Field>
          </div>
          <div className="grid grid-3">{inp("start_date", t2("pilot.start"), "date")}{inp("end_date", t2("pilot.end"), "date")}{inp("follow_up_due", t2("pilot.follow_up_due"), "date")}</div>
          <div className="grid grid-2">{inp("inclusion_criteria", t2("pilot.inclusion"))}{inp("exclusion_criteria", t2("pilot.exclusion"))}</div>
        </Card>
        <ActionError error={create.error} />
        <div className="row">
          <Button type="submit" variant="primary" disabled={!canDraft || create.isPending || !ivId || !f.topic_id || f.title.trim().length < 3}>{t2("pilot.create")}</Button>
        </div>
      </form>
    </div>
  );
}

export function PilotDetailPage() {
  const { id } = useParams();
  const { t2, lang, pick } = useMT();
  const q = usePilot(id);
  const nav = useNavigate();
  const { canDraft } = useRoles();
  const [note, setNote] = useState("");
  const [seed, setSeed] = useState("2027");
  const tr = useMAction<{ to_status: string; note: string; override_future_end: boolean }, PilotOut>("POST", () => `/api/v1/pilots/${id}/transition`);
  const [override, setOverride] = useState(false);
  const rnd = useMAction<{ seed: number; cohort_ids: string[] }, PilotOut>("POST", () => `/api/v1/pilots/${id}/randomize`);
  return (
    <div className="page stack">
      <MQuery q={q}>
        {(p) => (
          <>
            <div className="page-header">
              <div>
                <h1>{p.title}</h1>
                <p className="muted small"><span className="mono">{p.code}</span> · <PilotStatusBadge status={p.status} /> · {t2(`pilot.design.${p.design}`)} ·{" "}
                  {t2("pilot.ceiling")}: <strong><LabelText label={p.causal_ceiling} /></strong></p>
              </div>
              <div className="row">
                <Button onClick={() => nav("/portfolio/interventions")}>{t2("common.back")}</Button>
                <Button onClick={() => nav(`/pilots/${p.id}/fidelity`)} disabled={p.status === "draft" || p.status === "ready"}>{t2("pilot.fidelity")}</Button>
                <Button variant="primary" onClick={() => nav(`/pilots/${p.id}/follow-up`)}>{t2("pilot.followup")}</Button>
              </div>
            </div>
            <Alert tone={p.analysis_mode === "built_in" ? "info" : "warn"} role="note">{t2(`pilot.analysis_mode.${p.analysis_mode}`)}</Alert>
            {(p.status === "draft" || p.status === "ready") && (
              <Card title={t2("pilot.validation")}>
                {p.validation.ok ? <Alert tone="ok">{t2("pilot.valid")}</Alert> : <Messages items={(p.validation.errors as never) ?? []} />}
                <Messages items={(p.validation.warnings as never) ?? []} />
              </Card>
            )}
            <Card title={t2("common.actions")}>
              <div className="row" role="group" aria-label={t2("common.actions")}>
                {p.allowed_transitions.length === 0 && <span className="small muted">—</span>}
                {p.allowed_transitions.map((to) => (
                  <Button key={to} variant={to === "stopped" ? "danger" : to === "active" || to === "ready" ? "primary" : "default"}
                    disabled={tr.isPending || (to === "stopped" && note.trim().length < 3)} onClick={() => tr.mutate({ to_status: to, note, override_future_end: override })}>
                    {t2(`pilot.to.${to}`)}
                  </Button>
                ))}
                {p.allowed_transitions.includes("completed") && p.end_date && p.end_date > new Date().toISOString().slice(0, 10) && (
                  <label className="row small" style={{ gap: 4 }}>
                    <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> {t2("pilot.override_end")}
                  </label>
                )}
                {(p.allowed_transitions.includes("stopped") || override) && (
                  <input className="input" style={{ maxWidth: 320 }} aria-label={t2("pilot.stop_reason")} placeholder={t2("pilot.stop_reason")} value={note} onChange={(e) => setNote(e.target.value)} />
                )}
              </div>
              {p.status === "draft" && canDraft && (p.design === "cluster_randomized" || p.design === "stepped_wedge") && (
                <div className="row" style={{ marginTop: 8 }}>
                  <Field label={t2("pilot.seed")}>{(fid) => <input id={fid} className="input input-num" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />}</Field>
                  <Button onClick={() => rnd.mutate({ seed: Number(seed), cohort_ids: p.cohorts.map((c) => c.cohort_id) })} disabled={p.cohorts.length < 2}>{t2("pilot.randomize")}</Button>
                </div>
              )}
              {p.randomization && <p className="small">{t2("pilot.randomized", { seed: String(p.randomization.seed), unit: String(p.randomization.unit) })}</p>}
              <ActionError error={tr.error || rnd.error} />
            </Card>
            <SessionCalendar pilotId={p.id} />
            <div className="grid grid-2">
              <Card title={t2("pilot.title")}>
                <KV rows={[
                  [t2("pilot.intervention"), <Link key="i" to={`/interventions/${p.intervention_id}`}>{String(p.intervention_snapshot.title_ru ?? "")} · v{p.intervention_version}</Link>],
                  [t2("pilot.snapshot"), <span key="s" className="small">{p.snapshot_locked ? t2("pilot.locked") : t2("pilot.unlocked")} · <code className="xs">{p.snapshot_sha256.slice(0, 12)}</code></span>],
                  [t2("pilot.topic"), p.topic ? `${String(p.topic.code)} ${pick(p.topic as Record<string, unknown>, "title")}` : "—"],
                  [t2("pilot.objective"), p.objective ? `${String(p.objective.code)}` : "—"],
                  [t2("pilot.outcome"), p.primary_outcome_ru || "—"],
                  [t2("pilot.unit"), t2(`pilot.unit.${p.assignment_unit}`)],
                  [t2("pilot.baseline"), p.baseline_assessment ? `${String(p.baseline_assessment.code)} (${String(p.baseline_assessment.form_code)})` : "—"],
                  [t2("pilot.outcome_assessment"), p.outcome_assessment ? `${String(p.outcome_assessment.code)} (${String(p.outcome_assessment.form_code)})` : "—"],
                  [`${t2("pilot.start")} – ${t2("pilot.end")}`, `${p.start_date ?? "—"} – ${p.end_date ?? "—"}`],
                  [t2("pilot.follow_up_due"), p.follow_up_due ?? "—"],
                  [t2("pilot.owner"), p.owner || "—"],
                  [t2("iv.dosage"), t2("pilot.dosage", { m: p.planned.minutes_per_session, w: p.planned.sessions_per_week, n: p.planned.duration_weeks, s: p.planned.total_sessions })],
                  [t2("pilot.adjustment"), t2(`pilot.adjustment.${String(p.analysis_plan.adjustment ?? "none")}`)],
                  [t2("pilot.inclusion"), p.inclusion_criteria || "—"],
                  [t2("pilot.exclusion"), p.exclusion_criteria || "—"],
                ]} />
              </Card>
              <Card title={t2("pilot.cohorts")}>
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">{t2("pilot.cohorts")}</caption>
                    <thead><tr><th scope="col">{t2("pilot.cohorts")}</th><th scope="col">{t2("pilot.arm")}</th><th scope="col" className="num">{t2("pilot.n_learners")}</th></tr></thead>
                    <tbody>
                      {p.cohorts.map((c) => (
                        <tr key={c.cohort_id}><td className="mono">{c.code}</td><td>{t2(`pilot.arm.${c.arm}`)}{c.wave ? ` · ${t2("pilot.wave", { n: c.wave })}` : ""}</td><td className="num">{c.n_learners ?? "—"}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {p.latest_outcome && (
                  <p className="small" style={{ marginTop: 8 }}>{t2("pilot.latest_outcome")}: <OutcomeBadge status={String(p.latest_outcome.status)} />{" "}
                    <FidelityBadge code={String(p.latest_outcome.fidelity_class)} /></p>
                )}
                <h3 style={{ fontSize: "var(--text-sm)" }}>{t2("pilot.events")}</h3>
                <ol className="small" style={{ margin: 0 }}>
                  {p.events.map((e, i) => <li key={i}><Badge tone="neutral">{e.from_status ? `${t2(`pilot.status.${e.from_status}`)} → ` : `${t2("pilot.event.created")}: `}{t2(`pilot.status.${e.to_status}`)}</Badge> {dateTime(e.at, lang)} · {e.by ?? "—"} {e.note && `· ${e.note}`}</li>)}
                </ol>
              </Card>
            </div>
          </>
        )}
      </MQuery>
    </div>
  );
}
