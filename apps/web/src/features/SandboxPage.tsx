import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Envelope, IntentPreview, Op, SandboxResult, SandboxScenario } from "../api/wow";
import { useI18n } from "../i18n/I18n";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Loading } from "../ui";
import { pct } from "../ui/format";

interface Draft { name: string; ops: Op[]; text: string }

function opText(o: Op): string {
  const v = o.value ?? "";
  switch (o.op) {
    case "add": return `${o.topic} +${v} ч`;
    case "remove": return `${o.topic} −${v} ч`;
    case "set": return `${o.topic} = ${v} ч`;
    case "min": return `${o.topic} ≥ ${v} ч`;
    case "max": return `${o.topic} ≤ ${v} ч`;
    case "fix": return `${o.topic}: без изменений`;
    case "max_change": return `каждая тема ±${v} ч`;
    case "budget": return `бюджет ${v} ч`;
    case "priority": return `${o.topic}: приоритет ${v}`;
    default: return o.op;
  }
}

/** Decision Sandbox: plain-language intent → typed constraints (diff preview) → 2–3 scenarios side by side. */
export function SandboxPage({ readOnlyDemo }: { readOnlyDemo?: { text: string } }) {
  const { t, lang } = useI18n();
  const st = useAppState();
  const nav = useNavigate();
  const [text, setText] = useState(readOnlyDemo?.text ?? "");
  const [preview, setPreview] = useState<IntentPreview | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const intent = useMutation({
    mutationFn: (txt: string) => api.post<IntentPreview>("/api/v1/sandbox/intent", { dataset_id: st.datasetId, text: txt, lang }),
    onSuccess: setPreview,
  });
  const run = useMutation({
    mutationFn: (ds: Draft[]) => api.post<Envelope<SandboxResult>>("/api/v1/sandbox/run", { dataset_id: st.datasetId, filters: st.filters,
      scenarios: ds.map((d) => ({ name: d.name, ops: d.ops })) }),
  });
  if (!st.datasetId) return <div className="page"><EmptyState>{t("datasets.lead")}</EmptyState></div>;
  const addScenario = () => {
    if (!preview) return;
    const letter = "ABC"[drafts.length];
    setDrafts([...drafts, { name: `${letter}: ${text.slice(0, 60)}`, ops: preview.all_ops, text }]);
    setPreview(null);
    setText("");
  };
  const res = run.data?.result;
  return (
    <div className="page stack">
      <div className="page-header">
        <h1>{t("sandbox.title")}</h1>
        <p className="muted">{t("sandbox.lead")}</p>
      </div>
      <Card title={t("sandbox.intent")}>
        <form className="row" style={{ flexWrap: "nowrap" }} onSubmit={(e) => { e.preventDefault(); if (text.trim()) intent.mutate(text); }}>
          <label className="sr-only" htmlFor="sandbox-text">{t("sandbox.intent")}</label>
          <input id="sandbox-text" className="input" value={text} maxLength={500} onChange={(e) => setText(e.target.value)}
            placeholder={t("sandbox.placeholder")} data-testid="sandbox-text" />
          <Button type="submit" disabled={!text.trim() || intent.isPending || drafts.length >= 3} data-testid="sandbox-preview">{t("sandbox.preview")}</Button>
        </form>
        <p className="xs muted">{t("sandbox.examples")}</p>
        {intent.isError && <ErrorState error={intent.error} />}
        {preview && (
          <div className="stack" data-testid="sandbox-diff">
            <strong className="small">{t("sandbox.diff")}</strong>
            <ul className="small">
              {preview.ops.map((o, i) => <li key={i}><code>{opText(o)}</code></li>)}
            </ul>
            <table className="table xs">
              <thead><tr><th>{t("sandbox.topic")}</th><th>{t("sandbox.field")}</th><th>{t("sandbox.was")}</th><th>{t("sandbox.becomes")}</th></tr></thead>
              <tbody>{preview.diff.map((d, i) => <tr key={i}><td>{d.topic ?? "—"}</td><td className="mono">{d.field}</td><td>{String(d.before ?? "—")}</td><td><strong>{String(d.after)}</strong></td></tr>)}</tbody>
            </table>
            {preview.not_understood.length > 0 && (
              <Alert tone="warn" title={t("sandbox.not_understood")}>{preview.not_understood.join("; ")}</Alert>
            )}
            <div className="row">
              <Button variant="primary" onClick={addScenario} disabled={!preview.ops.length} data-testid="sandbox-add">{t("sandbox.add", { n: "ABC"[drafts.length] })}</Button>
              <Button variant="ghost" onClick={() => setPreview(null)}>{t("common.cancel")}</Button>
            </div>
          </div>
        )}
        {drafts.length > 0 && (
          <div className="stack" style={{ marginTop: 12 }}>
            {drafts.map((d, i) => (
              <div key={i} className="row small" style={{ gap: 6 }}>
                <Badge tone="info">{d.name}</Badge>
                <span className="mono xs">{d.ops.map(opText).join(" · ")}</span>
                <Button size="sm" variant="ghost" onClick={() => setDrafts(drafts.filter((_, j) => j !== i))} aria-label={t("common.remove")}>×</Button>
              </div>
            ))}
            <div className="row">
              <Button variant="primary" onClick={() => run.mutate(drafts)} disabled={run.isPending} data-testid="sandbox-run">{t("sandbox.run")}</Button>
            </div>
          </div>
        )}
      </Card>
      {run.isPending && <Loading />}
      {run.isError && <ErrorState error={run.error} />}
      {res && run.data && (
        <Card title={t("sandbox.compare")}>
          <p className="xs muted">{res.note_ru} · {t("sandbox.saved")} <code>{run.data.context.analysis_id.slice(0, 8)}</code></p>
          <div className="table-wrap" tabIndex={0}>
            <table className="table" data-testid="sandbox-table">
              <thead>
                <tr><th>{t("sandbox.topic")}</th><th className="num">{t("sandbox.before")}</th>
                  {res.scenarios.map((s) => <th key={s.name} className="num">{s.name}</th>)}</tr>
              </thead>
              <tbody>
                {res.topics.map((tp) => (
                  <tr key={tp.code}>
                    <td>{tp.code} {lang === "kz" ? tp.title_kz : tp.title_ru} {tp.score != null && <span className="xs muted">· {pct(tp.score, lang)}</span>}</td>
                    <td className="num">{res.before.hours[tp.code]}</td>
                    {res.scenarios.map((s) => {
                      const h = s.hours?.[tp.code];
                      const dlt = h != null ? h - res.before.hours[tp.code] : null;
                      return <td key={s.name} className="num">{h ?? "—"}{dlt ? <span className={dlt > 0 ? "delta-up" : "delta-down"}> ({dlt > 0 ? "+" : ""}{dlt})</span> : null}</td>;
                    })}
                  </tr>
                ))}
                <MetricRow label={t("sandbox.coverage")} before={`${res.before.metrics.objective_coverage.covered}/${res.before.metrics.objective_coverage.total}`}
                  cells={res.scenarios.map((s) => s.metrics ? `${s.metrics.objective_coverage.covered}/${s.metrics.objective_coverage.total}` : "—")} />
                <MetricRow label={t("sandbox.weak_hours")} before={String(res.before.metrics.hours_on_weak_topics)}
                  cells={res.scenarios.map((s) => (s.metrics ? String(s.metrics.hours_on_weak_topics) : "—"))} />
              </tbody>
            </table>
          </div>
          <div className="grid grid-3">
            {res.scenarios.map((s) => <ScenarioCard key={s.name} s={s} onDecision={() => {
              st.updateDraft({ planAnalysisId: s.plan_analysis_id, planPreset: "balanced" });
              nav("/decisions");
            }} readOnly={!!readOnlyDemo} />)}
          </div>
        </Card>
      )}
    </div>
  );
}

function MetricRow({ label, before, cells }: { label: string; before: string; cells: string[] }) {
  return <tr className="metric-row"><td><strong>{label}</strong></td><td className="num">{before}</td>{cells.map((c, i) => <td key={i} className="num">{c}</td>)}</tr>;
}

function ScenarioCard({ s, onDecision, readOnly }: { s: SandboxScenario; onDecision: () => void; readOnly: boolean }) {
  const { t } = useI18n();
  const ok = s.status === "optimal" || s.status === "feasible";
  const risks = [...(s.metrics?.risks ?? []), ...(s.metrics?.prerequisite_risks ?? [])];
  return (
    <div className="stack scenario-card" data-testid="sandbox-scenario">
      <div className="row" style={{ gap: 6 }}><strong>{s.name}</strong><Badge tone={ok ? "ok" : "danger"}>{s.status_message_ru}</Badge></div>
      {ok ? (
        <>
          <span className="xs muted">{t("sandbox.validator")}: {s.validation?.valid ? "✓" : "✗"}</span>
          {risks.length ? <ul className="small">{risks.map((r, i) => <li key={i}>⚠ {r.text_ru}</li>)}</ul> : <span className="small">{t("sandbox.no_risks")}</span>}
          {!readOnly && <Button size="sm" onClick={onDecision} data-testid="sandbox-to-decision">{t("sandbox.to_decision")}</Button>}
        </>
      ) : s.conflict ? (
        <div className="small" data-testid="sandbox-conflict">
          <strong>{t("sandbox.conflict")}:</strong>
          <ul>{s.conflict.constraints.map((c, i) => <li key={i}>{c.message_ru ?? c.label_ru ?? c.code}</li>)}</ul>
        </div>
      ) : null}
    </div>
  );
}
