import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, download } from "../api/client";
import { useCurrentDataset, useCurriculum, useDecision, useDecisions } from "../api/hooks";
import type { DecisionOut, FollowUpResponse, GenerationOut } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, Diff, EmptyState, ErrorState, Field, Loading, ModeBadge, QueryView, ReasonList, StatusBadge } from "../ui";
import { dateTime, num, pct, pp } from "../ui/format";
import { ImportWizard } from "./ImportPage";
import { NeedDataset } from "./OverviewPage";
import { LearningLoopCard, type LearningLoopSnapshot } from "./measurement/LearningLoopCard";

export function DecisionsPage() {
  const { t, lang } = useI18n();
  const { datasetId } = useAppState();
  const params = useParams();
  const list = useDecisions();
  const nav = useNavigate();
  if (!datasetId) return <NeedDataset />;
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t("decision.title")}</h1>
          <p className="muted">{t("decision.lead")}</p>
        </div>
        <Button variant="primary" onClick={() => nav("/decisions")}>{t("decision.new")}</Button>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "minmax(220px, 300px) 1fr" }}>
        <Card title={t("decision.list")}>
          <QueryView q={list} empty={(d) => d.length === 0}>
            {(rows) => (
              <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {rows.map((d) => (
                  <li key={d.id}>
                    <button type="button" className={`btn ${params.decisionId === d.id ? "btn-primary" : ""}`} style={{ width: "100%", justifyContent: "flex-start", textAlign: "left", whiteSpace: "normal", minHeight: 52 }} onClick={() => nav(`/decisions/${d.id}`)}>
                      <span>
                        <strong>{d.topic_code ?? "—"}</strong> · v{d.version} · {t(`decision.status.${d.status}` as DictKey)}
                        <br />
                        <span className="xs">{d.target_group} · {dateTime(d.created_at, lang)}</span>
                        {d.outcome_status && <><br /><span className="xs">{t(`followup.${d.outcome_status}` as DictKey)}</span></>}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QueryView>
          {list.data?.length === 0 && <p className="small muted">{t("decision.none")}</p>}
        </Card>
        {params.decisionId ? <DecisionDetail id={params.decisionId} /> : <NewDecision />}
      </div>
    </div>
  );
}

function NewDecision() {
  const { t, lang, pick } = useI18n();
  const st = useAppState();
  const cur = useCurriculum();
  const qc = useQueryClient();
  const nav = useNavigate();
  const d = st.draft;
  const edition = cur.data?.editions.find((e) => st.filters.edition_ids?.includes(e.id));
  const topic = cur.data?.topics.find((x) => x.id === st.topicId);
  const [form, setForm] = useState({
    target_group: edition ? `Классы, работающие по изданию ${edition.code}` : "Все классы набора",
    problem: "", hypothesis: "", action: "", responsible: "", follow_up_date: "", follow_up_criterion: "",
  });
  const [gen, setGen] = useState<GenerationOut | null>(null);
  const [busy, setBusy] = useState<"" | "rec" | "save">("");
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  async function recommend() {
    if (!d.topicAnalysisId) return;
    setBusy("rec");
    setError(null);
    try {
      const g = await api.post<GenerationOut>("/api/v1/ai/recommend", { topic_analysis_id: d.topicAnalysisId, comparison_analysis_id: d.comparisonAnalysisId ?? null, lang });
      setGen(g);
      const o = g.output as { problem: string; hypothesis: string; action: string; check: string };
      setForm((f) => ({ ...f, problem: o.problem, hypothesis: o.hypothesis, action: o.action, follow_up_criterion: o.check }));
      st.updateDraft({ generationId: g.generation_id, sourceIds: Array.from(new Set([...d.sourceIds, ...g.citations])) });
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }

  async function save() {
    setBusy("save");
    setError(null);
    try {
      const res = await api.post<DecisionOut>("/api/v1/decisions", {
        dataset_id: st.datasetId, topic_id: st.topicId, filters: st.filters, ...form, follow_up_date: form.follow_up_date || null,
        analysis_ids: [d.topicAnalysisId, d.comparisonAnalysisId].filter(Boolean), plan_analysis_id: d.planAnalysisId ?? null,
        plan_preset: d.planPreset ?? null, source_ids: d.sourceIds, generation_id: d.generationId ?? null,
      });
      await qc.invalidateQueries({ queryKey: ["decisions"] });
      st.resetDraft();
      nav(`/decisions/${res.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }
  const ready = !!d.topicAnalysisId && !!st.topicId && form.problem && form.hypothesis && form.action && form.responsible && form.target_group;
  return (
    <div className="stack">
      <Card title={t("decision.collected")}>
        <ul className="small" data-testid="draft-refs">
          <li>{t("nav.topic")}: {topic ? `${topic.code} ${pick(topic, "title")}` : "—"} {d.topicAnalysisId ? <code>{d.topicAnalysisId.slice(0, 8)}</code> : <Badge tone="warn">нет</Badge>}</li>
          <li>{t("nav.compare")}: {d.comparisonAnalysisId ? <code>{d.comparisonAnalysisId.slice(0, 8)}</code> : "—"}</li>
          <li>{t("nav.planner")}: {d.planAnalysisId ? <><code>{d.planAnalysisId.slice(0, 8)}</code> · {t(`planner.preset.${d.planPreset}` as DictKey)}</> : "—"}</li>
          <li>{t("decision.sources")}: {d.sourceIds.length}</li>
        </ul>
        {!d.topicAnalysisId && <Alert tone="warn">{t("decision.missing")}</Alert>}
        <div className="row">
          <Button onClick={recommend} disabled={!d.topicAnalysisId || busy !== ""} data-testid="draft-ai">{t("decision.draft_ai")}</Button>
          {gen && <ModeBadge mode={gen.mode} fallback={gen.fallback_reason} />}
        </div>
      </Card>
      <Card title={t("decision.new")}>
        <div className="stack">
          <Field label={t("decision.target_group")}>{(id) => <input id={id} className="input" value={form.target_group} onChange={(e) => set("target_group", e.target.value)} />}</Field>
          <Field label={t("decision.problem")}>{(id) => <textarea id={id} className="input" value={form.problem} onChange={(e) => set("problem", e.target.value)} data-testid="f-problem" />}</Field>
          <Field label={t("decision.hypothesis")}>{(id) => <textarea id={id} className="input" value={form.hypothesis} onChange={(e) => set("hypothesis", e.target.value)} />}</Field>
          <Field label={t("decision.action")}>{(id) => <textarea id={id} className="input" value={form.action} onChange={(e) => set("action", e.target.value)} />}</Field>
          <div className="grid grid-3">
            <Field label={t("decision.responsible")}>{(id) => <input id={id} className="input" value={form.responsible} onChange={(e) => set("responsible", e.target.value)} data-testid="f-responsible" />}</Field>
            <Field label={t("decision.follow_up_date")}>{(id) => <input id={id} className="input" type="date" value={form.follow_up_date} onChange={(e) => set("follow_up_date", e.target.value)} />}</Field>
            <Field label={t("decision.criterion")}>{(id) => <input id={id} className="input" value={form.follow_up_criterion} onChange={(e) => set("follow_up_criterion", e.target.value)} />}</Field>
          </div>
          <div className="row">
            <Button variant="primary" onClick={save} disabled={!ready || busy !== ""} data-testid="save-decision">{t("decision.save")}</Button>
            {busy && <Loading />}
          </div>
          {error ? <ErrorState error={error} /> : null}
        </div>
      </Card>
    </div>
  );
}

function DecisionDetail({ id }: { id: string }) {
  const { t, lang } = useI18n();
  const q = useDecision(id);
  const { user } = useAppState();
  const { dataset } = useCurrentDataset();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [fu, setFu] = useState<FollowUpResponse | null>(null);
  const isApprover = !!user?.roles.includes("approver");

  async function approve() {
    setBusy("approve");
    setError(null);
    try {
      const r = await api.post<DecisionOut>(`/api/v1/decisions/${id}/approve`, { note });
      await qc.invalidateQueries({ queryKey: ["decisions"] });
      nav(`/decisions/${r.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }
  async function runFollowUp() {
    setBusy("fu");
    setError(null);
    try {
      const r = await api.post<FollowUpResponse>(`/api/v1/decisions/${id}/follow-up`, {});
      setFu(r);
      await qc.invalidateQueries({ queryKey: ["decision", id] });
      await qc.invalidateQueries({ queryKey: ["decisions"] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }
  async function exp(fmt: string) {
    setError(null);
    try {
      await download(`/api/v1/decisions/${id}/report?format=${fmt}`, `decision.${fmt}`);
    } catch (e) {
      setError(e);
    }
  }
  return (
    <QueryView q={q}>
      {(d) => {
        const s = d.snapshot as unknown as Snapshot;
        const latest = d.history[d.history.length - 1]?.id === d.id;
        return (
          <div className="stack" data-testid="decision-detail">
            <Card title={`${t("decision.title")} · v${d.version}`} actions={<StatusBadge status={d.status} labelKey={`decision.status.${d.status}` as DictKey} />}>
              {d.is_synthetic && <Alert tone="info">{t("synthetic.note")}</Alert>}
              {d.is_stale && <div style={{ marginTop: 8 }}><Alert tone="warn" title={t("stale.title")}>{d.status === "draft" ? t("decision.stale") : t("decision.stale_approved")} (v{d.dataset_version} → v{d.current_dataset_version})</Alert></div>}
              <dl className="kv" style={{ marginTop: 12 }}>
                <dt>{t("decision.target_group")}</dt><dd>{d.target_group}</dd>
                <dt>{t("decision.problem")}</dt><dd>{d.problem}</dd>
                <dt>{t("decision.hypothesis")}</dt><dd>{d.hypothesis}</dd>
                <dt>{t("decision.action")}</dt><dd>{d.action}</dd>
                <dt>{t("decision.responsible")}</dt><dd>{d.responsible}</dd>
                <dt>{t("decision.follow_up_date")}</dt><dd>{d.follow_up_date ?? "—"}</dd>
                <dt>{t("decision.criterion")}</dt><dd>{d.follow_up_criterion || "—"}</dd>
                <dt>{t("header.version")}</dt><dd>v{d.dataset_version} · {dateTime(d.created_at, lang)} · {d.created_by}</dd>
                {d.approved_at && <><dt>{t("decision.status.approved")}</dt><dd>{d.approved_by} · {dateTime(d.approved_at, lang)} {d.approval_note ? `· «${d.approval_note}»` : ""}</dd></>}
              </dl>
              {d.status === "draft" && latest && (
                <div className="row" style={{ marginTop: 12 }}>
                  <input className="input" style={{ maxWidth: 360 }} placeholder={t("decision.approve_note")} aria-label={t("decision.approve_note")} value={note} onChange={(e) => setNote(e.target.value)} />
                  <Button variant="primary" onClick={approve} disabled={!isApprover || d.is_stale || busy !== ""} data-testid="approve">{t("decision.approve")}</Button>
                  {!isApprover && <span className="xs muted">{t("login.viewer")}</span>}
                </div>
              )}
              <div className="row" style={{ marginTop: 12 }}>
                <span className="small muted">{t("decision.export")}:</span>
                <Button size="sm" onClick={() => exp("pdf")} data-testid="export-pdf">{t("decision.export_pdf")}</Button>
                <Button size="sm" onClick={() => exp("csv")}>{t("decision.export_csv")}</Button>
                <Button size="sm" onClick={() => exp("xlsx")}>{t("decision.export_xlsx")}</Button>
              </div>
              {error ? <ErrorState error={error} /> : null}
            </Card>
            <SnapshotView s={s} />
            <LearningLoopCard loop={(d.snapshot as { learning_loop?: LearningLoopSnapshot }).learning_loop} />
            <Card title={t("decision.history")}>
              <ol className="small">
                {d.history.map((h) => <li key={h.id as string}>v{h.version as number} · {t(`decision.status.${h.status}` as DictKey)} · {dateTime(h.created_at as string, lang)}{h.approved_by ? ` · ${h.approved_by}` : ""}</li>)}
              </ol>
            </Card>
            <Card title={t("decision.followup")}>
              <p className="small muted">{t("decision.followup_lead")}</p>
              {(d.follow_ups.length > 0 || fu) && <FollowUpView r={(fu?.result ?? d.follow_ups[d.follow_ups.length - 1]?.result) as FollowUpResult} />}
              <div className="row" style={{ margin: "12px 0" }}>
                <Button variant="primary" onClick={runFollowUp} disabled={busy !== ""} data-testid="run-followup">{t("decision.followup_run")}</Button>
                {busy === "fu" && <Loading />}
              </div>
              {dataset && <ImportWizard fixedTarget="current" onCommitted={() => qc.invalidateQueries({ queryKey: ["decision", id] })} />}
            </Card>
          </div>
        );
      }}
    </QueryView>
  );
}

interface Snapshot {
  dataset: { name_ru: string; version: number; is_synthetic: boolean };
  topic?: { code: string; title_ru: string; status: string; summary: { mean: number; ci_low: number | null; ci_high: number | null; n_learners: number; n_classes: number; n_schools: number } | null;
    objectives: { code: string; text_ru: string; status: string; mean: number | null }[]; misconceptions: { code: string; label_ru: string; n_learners: number; share_of_learners: number | null }[] };
  comparison?: { editions: { a: { code: string }; b: { code: string } }; status: string; inference_level: string; raw: { a: { mean: number | null }; b: { mean: number | null }; difference: number | null };
    adjusted: { a: number | null; b: number | null; difference: number | null }; uncertainty: { adjusted_difference_ci: { low: number; high: number } | null; unavailable_reason: string | null };
    reasons: { code: string; severity: string; message_ru: string; message_kz: string }[] };
  plan?: { preset: string; status: string; changes: { code: string; before: number; after: number; delta: number }[]; total_before: number; total_after: number; validation: { valid: boolean } };
  sources: { source_id: string; document_filename: string; edition: { code: string; title: string } | null; page_printed: string | null; page_physical: number | null; anchor: string; text: string }[];
  limitations: string[];
  analyses: { analysis_id: string; kind: string; dataset_version: number; method_version: string }[];
  ai?: { mode: string; task: string };
}

function SnapshotView({ s }: { s: Snapshot }) {
  const { t, lang } = useI18n();
  return (
    <>
      <Card title={t("decision.evidence")}>
        {s.topic && s.topic.summary && (
          <div className="stack">
            <strong>{s.topic.code} {s.topic.title_ru}: {pct(s.topic.summary.mean, lang)} ({num(s.topic.summary.n_learners, lang)} {t("common.learners")}, {s.topic.summary.n_classes} {t("common.classes")})</strong>
            <ul className="small">{s.topic.objectives.map((o) => <li key={o.code}><code>{o.code}</code> {o.text_ru}: {pct(o.mean, lang)} <StatusBadge status={o.status} /></li>)}</ul>
            {s.topic.misconceptions.length > 0 && <ul className="small">{s.topic.misconceptions.map((m) => <li key={m.code}>{m.label_ru}: {m.n_learners} ({pct(m.share_of_learners, lang)})</li>)}</ul>}
          </div>
        )}
        {s.comparison && (
          <div className="stack" style={{ marginTop: 12 }}>
            <strong>{t("nav.compare")}: {s.comparison.editions.a.code} vs {s.comparison.editions.b.code} · {t(`comparability.${s.comparison.status}` as DictKey)} · {t(`inference.${s.comparison.inference_level}` as DictKey)}</strong>
            <span className="small">{t("compare.raw")}: {pct(s.comparison.raw.a.mean, lang)} / {pct(s.comparison.raw.b.mean, lang)} (<Diff value={s.comparison.raw.difference} />); {t("compare.adjusted")}: {pct(s.comparison.adjusted.a, lang)} / {pct(s.comparison.adjusted.b, lang)} (<Diff value={s.comparison.adjusted.difference} />)
              {s.comparison.uncertainty.adjusted_difference_ci ? `; ${t("common.ci95")} ${pp(s.comparison.uncertainty.adjusted_difference_ci.low, lang)} … ${pp(s.comparison.uncertainty.adjusted_difference_ci.high, lang)}` : ""}</span>
            <ReasonList reasons={s.comparison.reasons.filter((r) => r.severity !== "info")} />
          </div>
        )}
        <p className="xs muted" style={{ marginTop: 8 }}>{s.analyses.map((a) => `${a.kind} ${a.analysis_id.slice(0, 8)} (v${a.dataset_version}, ${a.method_version})`).join(" · ")}{s.ai ? ` · AI: ${s.ai.task} / ${s.ai.mode}` : ""}</p>
      </Card>
      {s.plan && (
        <Card title={t("decision.hours")}>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>{t("planner.topic")}</th><th className="num">{t("planner.before")}</th><th className="num">{t("planner.after")}</th><th className="num">{t("planner.delta")}</th></tr></thead>
              <tbody>{s.plan.changes.map((c) => <tr key={c.code}><td>{c.code}</td><td className="num">{c.before}</td><td className="num">{c.after}</td><td className="num">{c.delta > 0 ? `+${c.delta}` : c.delta}</td></tr>)}
                <tr><td><strong>{t("planner.total")}</strong></td><td className="num">{s.plan.total_before}</td><td className="num">{s.plan.total_after}</td><td /></tr></tbody>
            </table>
          </div>
          <p className="xs muted">{t(`planner.preset.${s.plan.preset}` as DictKey)} · {s.plan.status} · {s.plan.validation.valid ? t("planner.valid") : ""}</p>
        </Card>
      )}
      <Card title={t("decision.sources")}>
        {s.sources.length === 0 ? <EmptyState /> : (
          <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {s.sources.map((src) => (
              <li key={src.source_id}>
                <span className="small"><strong>{src.edition?.title ?? src.document_filename}</strong> · {src.page_printed ? `${t("materials.page")} ${src.page_printed} (${t("materials.page_physical")} ${src.page_physical})` : `${t("materials.anchor")} ${src.anchor}`}</span>
                <div className="quote">{src.text}</div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={t("decision.limits")}>
        <ul className="small">{Array.from(new Set(s.limitations)).map((l, i) => <li key={i}>{l}</li>)}</ul>
      </Card>
    </>
  );
}

interface Dyn {
  before: { raw: number | null; adjusted: number | null; n_learners: number; n_classes: number };
  after: { raw: number | null; adjusted: number | null; n_learners: number; n_classes: number };
  raw_change: number | null; adjusted_change: number | null; ci: { low: number; high: number } | null; ci_unavailable_reason: string | null;
}
interface FollowUpResult {
  status: string; target: Dyn; comparison_group: Dyn | null; difference_in_changes: number | null; note_ru: string; after_assessment: string; before_assessments: string[];
  comparability: { code: string; severity: string; message_ru: string; message_kz: string }[];
}

function FollowUpView({ r }: { r: FollowUpResult | null | undefined }) {
  const { t, lang } = useI18n();
  if (!r) return null;
  const row = (label: string, d: Dyn) => (
    <tr>
      <td>{label}</td>
      <td className="num">{pct(d.before.adjusted ?? d.before.raw, lang)} <span className="xs muted">(n={d.before.n_learners})</span></td>
      <td className="num">{pct(d.after.adjusted ?? d.after.raw, lang)} <span className="xs muted">(n={d.after.n_learners})</span></td>
      <td className="num"><Diff value={d.adjusted_change ?? d.raw_change} /></td>
      <td className="small">{d.ci ? `${pp(d.ci.low, lang)} … ${pp(d.ci.high, lang)}` : d.ci_unavailable_reason ?? "—"}</td>
    </tr>
  );
  return (
    <div className="stack" data-testid="followup-result">
      <div className="row"><StatusBadge status={r.status} labelKey={`followup.${r.status}` as DictKey} /><span className="xs muted">{r.before_assessments.join(", ")} → {r.after_assessment}</span></div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th /><th className="num">{t("decision.before")}</th><th className="num">{t("decision.after")}</th><th className="num">{t("decision.change")}</th><th>{t("common.ci95")}</th></tr></thead>
          <tbody>
            {row(t("decision.target_group"), r.target)}
            {r.comparison_group && row(t("decision.comparison_group"), r.comparison_group)}
          </tbody>
        </table>
      </div>
      {r.difference_in_changes != null && <p className="small">{t("decision.did")}: <Diff value={r.difference_in_changes} /></p>}
      <ReasonList reasons={r.comparability} />
      <Alert tone="info">{lang === "kz" ? t("decision.followup_note") : r.note_ru}</Alert>
    </div>
  );
}
