import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAppState } from "../../state/AppState";
import { Alert, Badge, Button, Card, Field, Select } from "../../ui";
import { useLearning, usePilots, usePortfolio } from "../measurement/api";
import { CodeLabel, FidelityBadge, MQuery, Messages, OutcomeBadge, Pager, PilotStatusBadge, useRoles, useUrlState } from "../measurement/components";
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
                          </Link> — <span className="small">{String(a.title)}</span> <span className="mono xs muted">{String(a.code)}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </Card>
                <Card title={t2("pf.followups")}>
                  {([["overdue", fu.overdue], ["due", fu.due_within_14_days], ["upcoming", fu.upcoming]] as const).map(([k, rows]) => (
                    <div key={k}>
                      <h3 style={{ fontSize: "var(--text-sm)", marginBottom: 4 }}>{t2(`pf.${k}`)} ({rows.length})</h3>
                      <ul className="small" style={{ margin: 0 }}>{rows.map((r) => <li key={r.pilot_id}><Link to={`/pilots/${r.pilot_id}`} aria-label={`${r.title}: ${r.code}`}>{r.title}</Link> <span className="mono xs muted">{r.code}</span> · {r.follow_up_due}</li>)}</ul>
                    </div>
                  ))}
                </Card>
              </div>
              <div className="grid grid-2">
                <Card title={t2("pf.missing")}>
                  <ul className="small" style={{ margin: 0 }}>
                    {d.missing_for_conclusions.map((m) => <li key={String(m.pilot_id)}><Link to={`/pilots/${String(m.pilot_id)}`} aria-label={`${String(m.title)}: ${String(m.code)}`}>{String(m.title)}</Link> <span className="mono xs muted">{String(m.code)}</span>: {(m.missing as string[]).map((c, i) => <span key={c}>{i > 0 && ", "}<CodeLabel prefix="pf.missing." code={c} /></span>)}</li>)}
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
              <PilotTable datasetId={ds} />
              <div className="grid grid-2">
                <Card title={t2("pf.learners")}>
                  <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                    {Object.entries((d.learners_by_outcome_status as { cells: Record<string, { value: number | null; suppressed: boolean; reason: string | null }> }).cells ?? {})
                      .map(([k, c]) => <li key={k} className="spread"><OutcomeBadge status={k} /> <strong>{c.suppressed ? <span className="small muted">{t2("fu.suppressed")}</span> : c.value}</strong></li>)}
                  </ul>
                </Card>
                <Card title={t2("pf.synthetic")}>
                  <p className="small" style={{ margin: 0 }}>{t2("iv.accepted_synthetic")}: <strong>{String((d.synthetic_evidence as { accepted_entries: number }).accepted_entries)}</strong></p>
                  <ul className="small">
                    {((d.synthetic_evidence as { repeated_signals_demo_only: { intervention_id: string; code: string }[] }).repeated_signals_demo_only ?? []).map((r) => (
                      <li key={r.intervention_id}><Badge tone="synthetic">{t2("common.synthetic_demo")}</Badge> {r.code}</li>
                    ))}
                  </ul>
                </Card>
              </div>
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
                <ul className="small">{l.lessons.map((x) => <li key={String(x.conclusion_id)}>{String(x.lessons_ru || x.summary_ru)} <span className="mono xs muted">{String(x.pilot_code)}</span></li>)}</ul></div>
              <div><h3 style={{ fontSize: "var(--text-sm)" }}>{t2("pf.questions")}</h3>
                <ul className="small">{l.open_questions.map((x, i) => <li key={i}>{String(x.question)} <span className="mono xs muted">{String(x.pilot_code)}</span></li>)}</ul></div>
              <div><h3 style={{ fontSize: "var(--text-sm)" }}>{t2("pf.pending")}</h3>
                <ul className="small">{l.pending_evidence_reviews.map((x) => <li key={String(x.entry_id)}><OutcomeBadge status={String(x.outcome_status)} /> <span className="mono xs muted">{String(x.intervention_code)} · {String(x.pilot_code)}</span></li>)}</ul></div>
            </div>
          </Card>
        )}
      </MQuery>
    </div>
  );
}

const PAGE = 20;

function PilotTable({ datasetId }: { datasetId: string | null }) {
  const { t2 } = useMT();
  const [u, setU] = useUrlState({ pilots_offset: "0" });
  const offset = Number(u.pilots_offset) || 0;
  const q = usePilots(datasetId, PAGE, offset);
  return (
    <Card title={t2("pf.pilots")}>
      <MQuery q={q} empty={(d) => d.items.length === 0}>
        {(d) => (
          <div className="table-wrap">
            <table className="table" data-testid="pilots">
              <caption className="sr-only">{t2("pf.pilots")}</caption>
              <thead><tr><th scope="col">{t2("pilot.title")}</th><th scope="col">{t2("common.status")}</th><th scope="col">{t2("pilot.design")}</th>
                <th scope="col">{t2("pilot.intervention")}</th><th scope="col">{t2("pf.fidelity")}</th><th scope="col">{t2("pf.outcomes")}</th></tr></thead>
              <tbody>
                {d.items.map((p) => (
                  <tr key={p.id}>
                    <th scope="row"><Link to={`/pilots/${p.id}`} aria-label={`${p.code}: ${p.title}`}>{p.title}</Link> <span className="mono xs muted">{p.code}</span></th>
                    <td><PilotStatusBadge status={p.status} /></td><td className="small">{t2(`pilot.design.${p.design}`)}</td>
                    <td className="mono small">{String((p as Record<string, unknown>).intervention_code ?? "")} v{p.intervention_version}</td>
                    <td><FidelityBadge code={p.fidelity} /></td><td><OutcomeBadge status={p.outcome_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager total={d.total} limit={d.limit} offset={d.offset} onChange={(o) => setU({ pilots_offset: String(o) })} />
          </div>
        )}
      </MQuery>
    </Card>
  );
}
