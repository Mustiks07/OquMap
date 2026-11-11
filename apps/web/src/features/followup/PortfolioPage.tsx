import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAppState } from "../../state/AppState";
import { Alert, Button, Card, Field, Select } from "../../ui";
import { useLearning, usePortfolio } from "../measurement/api";
import { FidelityBadge, MQuery, Messages, OutcomeBadge, PilotStatusBadge, useRoles } from "../measurement/components";
import { useMT } from "../measurement/i18n";

type Ref = { pilot_id: string; code: string; title: string; status: string; follow_up_due: string | null };

export function PortfolioPage() {
  const { t2, pick } = useMT();
  const { datasetId } = useAppState();
  const [scope, setScope] = useState<"current" | "all">(datasetId ? "current" : "all");
  const ds = scope === "current" ? datasetId : null;
  const q = usePortfolio(ds);
  const learning = useLearning(ds);
  const nav = useNavigate();
  const { canDraft } = useRoles();
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t2("pf.title")}</h1>
          <p className="muted">{t2("pf.lead")}</p>
        </div>
        <div className="row">
          <Field label={t2("common.dataset")}>{(id) => <Select id={id} value={scope} onChange={(v) => setScope(v as "current" | "all")}
            options={[...(datasetId ? [{ value: "current", label: t2("common.current_dataset") }] : []), { value: "all", label: t2("common.all_datasets") }]} />}</Field>
          {canDraft && <Button variant="primary" onClick={() => nav("/pilots/new")}>{t2("nav.pilot_new")}</Button>}
        </div>
      </div>
      <MQuery q={q}>
        {(d) => {
          const fu = d.follow_ups as { overdue: Ref[]; due_within_14_days: Ref[]; upcoming: Ref[] };
          return (
            <>
              <div className="grid grid-3">
                <Card title={t2("pf.status_counts")}>
                  <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                    {Object.entries(d.counts_by_status).map(([k, v]) => <li key={k} className="spread"><PilotStatusBadge status={k} /> <strong>{v}</strong></li>)}
                  </ul>
                </Card>
                <Card title={t2("pf.fidelity")}>
                  <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                    {Object.entries(d.fidelity_distribution).map(([k, v]) => <li key={k} className="spread"><FidelityBadge code={k} /> <strong>{v}</strong></li>)}
                  </ul>
                </Card>
                <Card title={t2("pf.outcomes")}>
                  <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                    {Object.entries(d.outcome_distribution).map(([k, v]) => <li key={k} className="spread"><OutcomeBadge status={k} /> <strong>{v}</strong></li>)}
                  </ul>
                </Card>
              </div>
              <Alert tone="info">{t2("pf.best")}</Alert>
              <div className="grid grid-2">
                <Card title={t2("pf.queue")}>
                  {d.action_queue.length === 0 ? <p className="small muted">—</p> : (
                    <ol className="stack" style={{ margin: 0, paddingLeft: 18 }} data-testid="action-queue">
                      {d.action_queue.map((a, i) => (
                        <li key={i}>
                          <Link to={String(a.action).startsWith("run_follow") || a.action === "record_conclusion" || a.action === "review_evidence_entry" ? `/pilots/${String(a.pilot_id)}/follow-up` : `/pilots/${String(a.pilot_id)}`}>
                            {t2(`pf.action.${String(a.action)}`)}
                          </Link> — <span className="mono">{String(a.code)}</span> <span className="small">{String(a.title)}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </Card>
                <Card title={t2("pf.followups")}>
                  {([["overdue", fu.overdue], ["due", fu.due_within_14_days], ["upcoming", fu.upcoming]] as const).map(([k, rows]) => (
                    <div key={k}>
                      <h3 style={{ fontSize: "var(--text-sm)", marginBottom: 4 }}>{t2(`pf.${k}`)} ({rows.length})</h3>
                      <ul className="small" style={{ margin: 0 }}>{rows.map((r) => <li key={r.pilot_id}><Link to={`/pilots/${r.pilot_id}`}>{r.code}</Link> · {r.follow_up_due}</li>)}</ul>
                    </div>
                  ))}
                </Card>
              </div>
              <div className="grid grid-2">
                <Card title={t2("pf.missing")}>
                  <ul className="small" style={{ margin: 0 }}>
                    {d.missing_for_conclusions.map((m) => <li key={String(m.pilot_id)}><Link to={`/pilots/${String(m.pilot_id)}`}>{String(m.code)}</Link>: {(m.missing as string[]).join(", ")}</li>)}
                  </ul>
                </Card>
                <Card title={t2("pf.repeated")}>
                  {d.interventions_with_repeated_signals.length === 0 ? <p className="small muted">{t2("pf.no_repeated")}</p> : (
                    <ul className="small">{d.interventions_with_repeated_signals.map((r) => <li key={String(r.intervention_id)}><Link to={`/interventions/${String(r.intervention_id)}`}>{String(r.code)}</Link> ({String(r.comparable_positive_signals)})</li>)}</ul>
                  )}
                </Card>
              </div>
              <Card title={t2("pf.coverage")}>
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">{t2("pf.coverage")}</caption>
                    <thead><tr><th scope="col">{t2("pf.topic")}</th><th scope="col" className="num">{t2("iv.pilots")}</th><th scope="col" className="num">{t2("pilot.status.active")}</th>
                      <th scope="col" className="num">{t2("pf.with_outcome")}</th><th scope="col">{t2("pf.has_iv")}</th></tr></thead>
                    <tbody>
                      {((d.coverage as { topics: Record<string, unknown>[] }).topics ?? []).map((t) => (
                        <tr key={String(t.topic_id)}><td><span className="mono">{String(t.code)}</span> {pick(t, "title")}</td><td className="num">{String(t.pilots)}</td>
                          <td className="num">{String(t.active)}</td><td className="num">{String(t.with_outcome)}</td><td>{t.has_interventions ? t2("common.yes") : t2("common.none")}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card title={t2("pf.pilots")}>
                <div className="table-wrap">
                  <table className="table" data-testid="pilots">
                    <caption className="sr-only">{t2("pf.pilots")}</caption>
                    <thead><tr><th scope="col">{t2("pilot.title")}</th><th scope="col">{t2("common.status")}</th><th scope="col">{t2("pilot.design")}</th>
                      <th scope="col">{t2("pilot.intervention")}</th><th scope="col">{t2("pf.fidelity")}</th><th scope="col">{t2("pf.outcomes")}</th></tr></thead>
                    <tbody>
                      {d.pilots.map((p) => (
                        <tr key={p.id} className="clickable" onClick={() => nav(`/pilots/${p.id}`)}>
                          <td><Link to={`/pilots/${p.id}`} onClick={(e) => e.stopPropagation()} className="mono">{p.code}</Link> <span className="small">{p.title}</span></td>
                          <td><PilotStatusBadge status={p.status} /></td><td className="small">{t2(`pilot.design.${p.design}`)}</td>
                          <td className="mono small">{String((p as Record<string, unknown>).intervention_code ?? "")} v{p.intervention_version}</td>
                          <td><FidelityBadge code={p.fidelity} /></td><td><OutcomeBadge status={p.outcome_status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Messages items={d.limitations} />
            </>
          );
        }}
      </MQuery>
      <MQuery q={learning}>
        {(l) => (
          <Card title={t2("pf.learning")}>
            <p className="xs muted">{l.note_ru}</p>
            <div className="grid grid-3">
              <div><h3 style={{ fontSize: "var(--text-sm)" }}>{t2("pf.lessons")}</h3>
                <ul className="small">{l.lessons.map((x) => <li key={String(x.conclusion_id)}><span className="mono">{String(x.pilot_code)}</span>: {String(x.lessons_ru || x.summary_ru)}</li>)}</ul></div>
              <div><h3 style={{ fontSize: "var(--text-sm)" }}>{t2("pf.questions")}</h3>
                <ul className="small">{l.open_questions.map((x, i) => <li key={i}><span className="mono">{String(x.pilot_code)}</span>: {String(x.question)}</li>)}</ul></div>
              <div><h3 style={{ fontSize: "var(--text-sm)" }}>{t2("pf.pending")}</h3>
                <ul className="small">{l.pending_evidence_reviews.map((x) => <li key={String(x.entry_id)}>{String(x.intervention_code)} · {String(x.pilot_code)} · <OutcomeBadge status={String(x.outcome_status)} /></li>)}</ul></div>
            </div>
          </Card>
        )}
      </MQuery>
    </div>
  );
}
