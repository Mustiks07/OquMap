import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useCurriculum } from "../../api/hooks";
import { Alert, Badge, Button, Card, Field, Metric, Select } from "../../ui";
import { dateTime } from "../../ui/format";
import {
  useConclusions, useMAction, useOutcomes, usePilot, type ConclusionCreate, type ConclusionOut, type PilotOutcomeOut,
} from "../measurement/api";
import { ActionError, CIRange, FidelityBadge, KV, LabelText, MQuery, Messages, Num, OutcomeBadge, PP, Share, useRoles } from "../measurement/components";
import { useMT } from "../measurement/i18n";

type Arm = { assigned: number; matched: number; attrition: number; baseline_mean: number | null; outcome_mean: number | null;
  change: { mean: number | null; ci_low: number | null; ci_high: number | null; ci_unavailable_reason: string | null; n_clusters: number } };

function OutcomeView({ o }: { o: PilotOutcomeOut }) {
  const { t2, lang } = useMT();
  const r = o.result as Record<string, unknown>;
  const primary = r.primary as { estimand: string; estimate: number | null; ci_low: number | null; ci_high: number | null; ci_unavailable_reason: string | null; source: string };
  const arms = (r.arms ?? {}) as Record<string, Arm>;
  const cohorts = r.cohorts as { cohort_id: string; code: string; arm: string; n_matched: number | null; mean_change: number | null; suppressed: boolean }[] | null;
  return (
    <div className="stack" data-testid="outcome">
      {o.interim && <Alert tone="warn">{t2("fu.interim")}</Alert>}
      {o.is_stale && <Alert tone="warn">{t2("fu.stale")}</Alert>}
      <div className="grid grid-4">
        <Metric label={t2("common.status")} value={<OutcomeBadge status={o.status} />} sub={(r.status_rules_fired as string[]).join(", ")} />
        <Metric label={t2("fu.causal")} value={<span className="small"><LabelText label={o.causal_level} /></span>} sub={<>{t2("fu.ceiling")}: <LabelText label={o.causal_ceiling} /></>} />
        <Metric label={t2("fu.fidelity")} value={<FidelityBadge code={o.fidelity.code} />} sub={`${o.method_version} · v${o.dataset_version}`} />
        <Metric label={t2(`fu.estimand.${primary.estimand}`)} value={<PP v={primary.estimate} />}
          sub={<><CIRange low={primary.ci_low} high={primary.ci_high} reason={primary.ci_unavailable_reason} asPP /> · {t2(`fu.source.${primary.source}`)}</>} />
      </div>
      <Alert tone={o.status === "positive_signal" ? "ok" : o.status.startsWith("invalid") ? "danger" : "info"}>{String(r.interpretation_ru)}</Alert>
      {Object.keys(arms).length > 0 && (
        <div className="table-wrap">
          <table className="table" data-testid="outcome-arms">
            <caption className="sr-only">{t2("fu.arms")}</caption>
            <thead><tr>
              <th scope="col">{t2("fu.arms")}</th><th scope="col" className="num">{t2("fu.assigned")}</th><th scope="col" className="num">{t2("fu.matched")}</th>
              <th scope="col" className="num">{t2("fu.attrition")}</th><th scope="col" className="num">{t2("fu.before")}</th><th scope="col" className="num">{t2("fu.after")}</th>
              <th scope="col" className="num">{t2("fu.change")}</th><th scope="col">95%</th>
            </tr></thead>
            <tbody>
              {Object.entries(arms).map(([arm, a]) => (
                <tr key={arm}>
                  <td>{t2(`pilot.arm.${arm}`)}</td><td className="num"><Num v={a.assigned} /></td><td className="num"><Num v={a.matched} /></td>
                  <td className="num"><Share v={a.attrition} /></td><td className="num"><Share v={a.baseline_mean} /></td><td className="num"><Share v={a.outcome_mean} /></td>
                  <td className="num"><PP v={a.change.mean} /></td>
                  <td><CIRange low={a.change.ci_low} high={a.change.ci_high} reason={a.change.ci_unavailable_reason} asPP /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <KV rows={[
        [t2("fu.comparability"), <span key="c" className="mono small">{String((r.comparability as { code: string }).code)} · {String(r.n_outcome_items)} items</span>],
        [t2("fu.attrition"), <Share key="a" v={r.attrition as number | null} />],
        [t2("common.generated"), dateTime(o.created_at, lang)],
      ]} />
      {cohorts && (
        <details>
          <summary className="small">{t2("fu.cohorts")}</summary>
          <ul className="small">
            {cohorts.map((c) => <li key={c.cohort_id}><span className="mono">{c.code}</span> ({t2(`pilot.arm.${c.arm}`)}): {c.suppressed ? "—" : <PP v={c.mean_change} />} {c.n_matched ? `n=${c.n_matched}` : ""}</li>)}
          </ul>
        </details>
      )}
      <Messages items={r.reasons as never} title={t2("fu.reasons")} />
    </div>
  );
}

function ConclusionForm({ pilotId, outcome, onSaved }: { pilotId: string; outcome: PilotOutcomeOut; onSaved: (c: ConclusionOut) => void }) {
  const { t2 } = useMT();
  const [f, setF] = useState({ decision: "continue" as ConclusionCreate["decision"], summary_ru: "", lessons_ru: "", questions: "", next_action_ru: "",
    create_next_decision_version: true, propose_evidence_update: true });
  const save = useMAction<ConclusionCreate, ConclusionOut>("POST", () => `/api/v1/pilots/${pilotId}/conclusions`);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const res = await save.mutateAsync({ outcome_id: outcome.id, decision: f.decision, summary_ru: f.summary_ru, summary_kz: "", lessons_ru: f.lessons_ru,
      open_questions: f.questions.split("\n").map((x) => x.trim()).filter(Boolean), evidence_ids: [], next_action_ru: f.next_action_ru,
      create_next_decision_version: f.create_next_decision_version, propose_evidence_update: f.propose_evidence_update });
    onSaved(res);
  }
  const area = (k: "summary_ru" | "lessons_ru" | "questions" | "next_action_ru", label: string) => (
    <Field label={label}>{(id) => <textarea id={id} className="input" maxLength={4000} value={f[k]} onChange={(e) => setF((x) => ({ ...x, [k]: e.target.value }))} />}</Field>
  );
  return (
    <form className="stack" onSubmit={submit} aria-label={t2("fu.conclusion")}>
      <Field label={t2("fu.decision")}>{(id) => <Select id={id} value={f.decision} onChange={(v) => setF((x) => ({ ...x, decision: v as ConclusionCreate["decision"] }))}
        options={(["continue", "modify", "stop", "extend_data_collection"] as const).map((d) => ({ value: d, label: t2(`fu.decision.${d}`) }))} />}</Field>
      {area("summary_ru", t2("fu.summary"))}
      {area("lessons_ru", t2("fu.lessons"))}
      {area("questions", t2("fu.questions"))}
      {area("next_action_ru", t2("fu.next_action"))}
      <label className="row small" style={{ gap: 6 }}><input type="checkbox" checked={f.create_next_decision_version}
        onChange={(e) => setF((x) => ({ ...x, create_next_decision_version: e.target.checked }))} /> {t2("fu.next_decision")}</label>
      <label className="row small" style={{ gap: 6 }}><input type="checkbox" checked={f.propose_evidence_update}
        onChange={(e) => setF((x) => ({ ...x, propose_evidence_update: e.target.checked }))} /> {t2("fu.propose_evidence")}</label>
      <ActionError error={save.error} />
      <Button type="submit" variant="primary" disabled={save.isPending || f.summary_ru.trim().length < 10}>{t2("fu.save_conclusion")}</Button>
    </form>
  );
}

export function FollowUpPage() {
  const { id } = useParams();
  const { t2, lang } = useMT();
  const pilot = usePilot(id);
  const outcomes = useOutcomes(id);
  const conclusions = useConclusions(id);
  const cur = useCurriculum();
  const nav = useNavigate();
  const { canDraft, canApprove } = useRoles();
  const [assessment, setAssessment] = useState("");
  const run = useMAction<{ outcome_assessment_id: string | null }, PilotOutcomeOut>("POST", () => `/api/v1/pilots/${id}/follow-up`);
  const review = useMAction<{ entry: string; accept: boolean; note: string }, unknown>("POST", (b) => `/api/v1/intervention-evidence/${b.entry}/review`, (b) => ({ accept: b.accept, note: b.note }));
  const [note, setNote] = useState("");
  const p = pilot.data;
  const running = p?.status === "active" || p?.status === "completed";
  const latest = outcomes.data?.[0];
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t2("fu.title", { code: p?.code ?? "" })}</h1>
          <p className="muted">{t2("fu.lead")}</p>
        </div>
        <Button onClick={() => nav(`/pilots/${id}`)}>{t2("common.back")}</Button>
      </div>
      <MQuery q={pilot}>
        {(pl) => (
          <Card title={t2("fu.outcome_assessment")}>
            {!running ? <Alert tone="info">{t2("fu.not_running")}</Alert> : (
              <div className="row">
                <Field label={t2("fu.outcome_assessment")}>
                  {(fid) => <Select id={fid} value={assessment || (pl.outcome_assessment?.assessment_id as string) || ""} onChange={setAssessment}
                    options={[{ value: "", label: "—" }, ...(cur.data?.assessments ?? []).map((a) => ({ value: a.id, label: `${a.code} (${a.form}/${a.scale})` }))]} />}
                </Field>
                <Button variant="primary" disabled={!canDraft || run.isPending} onClick={() => run.mutate({ outcome_assessment_id: assessment || null })}>{t2("fu.run")}</Button>
              </div>
            )}
            <ActionError error={run.error} />
          </Card>
        )}
      </MQuery>
      <MQuery q={outcomes} empty={(d) => d.length === 0} emptyText={t2("fu.no_outcome")}>
        {(list) => (
          <>
            <Card title={t2("pilot.latest_outcome")}><OutcomeView o={list[0]} /></Card>
            {list.length > 1 && (
              <Card title={t2("fu.history")}>
                <ul className="small">{list.slice(1).map((o) => <li key={o.id}><OutcomeBadge status={o.status} /> {dateTime(o.created_at, lang)} · v{o.dataset_version}{o.interim ? " · interim" : ""}</li>)}</ul>
              </Card>
            )}
          </>
        )}
      </MQuery>
      {latest && canDraft && !latest.interim && (
        <Card title={t2("fu.conclusion")}><ConclusionForm pilotId={id!} outcome={latest} onSaved={() => undefined} /></Card>
      )}
      <MQuery q={conclusions} empty={(d) => d.length === 0} emptyText="—">
        {(list) => (
          <Card title={t2("fu.conclusions")}>
            <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }} data-testid="conclusions">
              {list.map((c) => (
                <li key={c.id} className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: 8 }}>
                  <div className="row"><Badge tone="info">{t2(`fu.decision.${c.decision}`)}</Badge> <OutcomeBadge status={c.outcome_status} />
                    <span className="xs muted">{dateTime(c.created_at, lang)} · {c.created_by ?? "—"}</span></div>
                  <p style={{ margin: 0 }}>{c.summary_ru}</p>
                  {c.lessons_ru && <p className="small" style={{ margin: 0 }}>{t2("fu.lessons")}: {c.lessons_ru}</p>}
                  {c.open_questions.length > 0 && <ul className="small" style={{ margin: 0 }}>{c.open_questions.map((q2, i) => <li key={i}>{q2}</li>)}</ul>}
                  <p className="xs muted" style={{ margin: 0 }}>{t2("fu.evidence_ids")}: {c.evidence_ids.map((e) => e.slice(0, 8)).join(", ")}</p>
                  <div className="row">
                    {c.next_decision_id && <Link to={`/decisions/${c.next_decision_id}`}>{t2("fu.open_decision")}</Link>}
                    {c.evidence_entry && <Badge tone={c.evidence_entry.review_status === "accepted" ? "ok" : "neutral"}>{String(c.evidence_entry.review_status)}</Badge>}
                    {c.evidence_entry?.review_status === "proposed" && canApprove && (
                      <>
                        <input className="input" style={{ maxWidth: 280 }} aria-label={t2("fu.review_note")} placeholder={t2("fu.review_note")} value={note} onChange={(e) => setNote(e.target.value)} />
                        <Button size="sm" onClick={() => review.mutate({ entry: String(c.evidence_entry!.id), accept: true, note })}>{t2("fu.accept")}</Button>
                        <Button size="sm" onClick={() => review.mutate({ entry: String(c.evidence_entry!.id), accept: false, note })}>{t2("fu.reject")}</Button>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            <ActionError error={review.error} />
          </Card>
        )}
      </MQuery>
    </div>
  );
}
