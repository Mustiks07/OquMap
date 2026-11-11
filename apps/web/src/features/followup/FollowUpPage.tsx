import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useCurriculum } from "../../api/hooks";
import { Alert, Badge, Button, Card, Field, Metric, Select } from "../../ui";
import { dateTime } from "../../ui/format";
import {
  useConclusions, useMAction, useOutcomes, usePilot, type ConclusionCreate, type ConclusionOut, type PilotOutcomeOut,
} from "../measurement/api";
import { ActionError, CIRange, CodeLabel, FidelityBadge, KV, LabelText, MQuery, Messages, Num, OutcomeBadge, PP, Share, useRoles } from "../measurement/components";
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
        <Metric label={t2("common.status")} value={<OutcomeBadge status={o.status} />} sub={<>{(r.status_rules_fired as string[]).map((c, i) => <span key={c}>{i > 0 && ", "}<CodeLabel prefix="rule." code={c} /></span>)}</>} />
        <Metric label={t2("fu.causal")} value={<span className="small"><LabelText label={o.causal_level} /></span>} sub={<>{t2("fu.ceiling")}: <LabelText label={o.causal_ceiling} /></>} />
        <Metric label={t2("fu.fidelity")} value={<FidelityBadge code={o.fidelity.code} />} sub={`${o.method_version} · v${o.dataset_version}`} />
        <Metric label={t2(`fu.estimand.${primary.estimand}`)} value={<PP v={primary.estimate} />}
          sub={<><CIRange low={primary.ci_low} high={primary.ci_high} reason={primary.ci_unavailable_reason} asPP /> · {t2(`fu.source.${primary.source}`)}</>} />
      </div>
      <Alert tone={o.status === "positive_signal" ? "ok" : o.status.startsWith("invalid") ? "danger" : "info"}>{String(r.interpretation_ru)}</Alert>
      {(r.suppression as { applied?: boolean } | undefined)?.applied && <Alert tone="info" role="note">{t2("fu.suppression_note")}</Alert>}
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
                  <th scope="row">{t2(`pilot.arm.${arm}`)}{(a as { suppressed?: boolean }).suppressed && <span className="xs muted"> — {t2("fu.suppressed")}</span>}</th><td className="num"><Num v={a.assigned} /></td><td className="num"><Num v={a.matched} /></td>
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
        [t2("fu.comparability"), <span key="c" className="small"><CodeLabel prefix="fu.cmp." code={String((r.comparability as { code: string }).code)} /> · {t2("fu.items_n", { n: Number(r.n_outcome_items) })}</span>],
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

const UNINTERPRETABLE = new Set(["invalid_due_to_fidelity", "invalid_due_to_comparability", "needs_more_data"]);
const STANDARD_ACKS = ["no_effectiveness_conclusion", "requires_new_pilot_or_implementation", "synthetic_data_only", "observational_design", "interim_result"];

function ConclusionForm({ pilotId, outcome, onSaved }: { pilotId: string; outcome: PilotOutcomeOut; onSaved: (c: ConclusionOut) => void }) {
  const { t2 } = useMT();
  const [f, setF] = useState({ decision: "continue" as ConclusionCreate["decision"], summary_ru: "", lessons_ru: "", questions: "", next_action_ru: "",
    create_next_decision_version: true, propose_evidence_update: true,
    decision_basis: (UNINTERPRETABLE.has(outcome.status) ? "insufficient_evidence" : "evidence_supports") as ConclusionCreate["decision_basis"],
    stop_reason_code: "" as string, acks: [] as string[] });
  const reasonCodes = ((outcome.result as { reasons?: { code: string; severity: string }[] }).reasons ?? [])
    .filter((x) => x.severity !== "info").map((x) => x.code);
  const ackOptions = Array.from(new Set([...STANDARD_ACKS, ...reasonCodes]));
  const save = useMAction<ConclusionCreate, ConclusionOut>("POST", () => `/api/v1/pilots/${pilotId}/conclusions`);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const res = await save.mutateAsync({ outcome_id: outcome.id, decision: f.decision, summary_ru: f.summary_ru, summary_kz: "", lessons_ru: f.lessons_ru,
      open_questions: f.questions.split("\n").map((x) => x.trim()).filter(Boolean), evidence_ids: [], next_action_ru: f.next_action_ru,
      create_next_decision_version: f.create_next_decision_version, propose_evidence_update: f.propose_evidence_update,
      decision_basis: f.decision_basis, acknowledged_limitation_codes: f.acks,
      stop_reason_code: f.decision === "stop" ? ((f.stop_reason_code || null) as ConclusionCreate["stop_reason_code"]) : null });
    onSaved(res);
  }
  const area = (k: "summary_ru" | "lessons_ru" | "questions" | "next_action_ru", label: string) => (
    <Field label={label}>{(id) => <textarea id={id} className="input" maxLength={4000} value={f[k]} onChange={(e) => setF((x) => ({ ...x, [k]: e.target.value }))} />}</Field>
  );
  return (
    <form className="stack" onSubmit={submit} aria-label={t2("fu.conclusion")}>
      <Field label={t2("fu.decision")}>{(id) => <Select id={id} value={f.decision} onChange={(v) => setF((x) => ({ ...x, decision: v as ConclusionCreate["decision"] }))}
        options={(["continue", "modify", "stop", "extend_data_collection"] as const).map((d) => ({ value: d, label: t2(`fu.decision.${d}`) }))} />}</Field>
      <Field label={t2("fu.basis")}>{(id) => <Select id={id} value={f.decision_basis ?? "insufficient_evidence"}
        onChange={(v) => setF((x) => ({ ...x, decision_basis: v as ConclusionCreate["decision_basis"] }))}
        options={(["evidence_supports", "operational", "insufficient_evidence", "external_factors"] as const)
          .filter((b) => !(UNINTERPRETABLE.has(outcome.status) && b === "evidence_supports"))
          .map((b) => ({ value: b, label: t2(`fu.basis.${b}`) }))} />}</Field>
      {f.decision === "stop" && (
        <Field label={t2("fu.stop_reason")}>{(id) => <Select id={id} value={f.stop_reason_code} onChange={(v) => setF((x) => ({ ...x, stop_reason_code: v }))}
          options={[{ value: "", label: "—" }, ...(["implementation_not_feasible", "resource_constraints", "priority_change", "safety_or_harm_concern",
            "replaced_by_alternative", "other"] as const).map((c) => ({ value: c, label: t2(`fu.stop.${c}`) }))]} />}</Field>
      )}
      <fieldset style={{ border: "1px solid var(--color-border)", borderRadius: 8, padding: 12 }}>
        <legend className="small">{t2("fu.acks")}</legend>
        <div className="stack">
          {ackOptions.map((code) => (
            <label key={code} className="row small" style={{ gap: 6 }}>
              <input type="checkbox" checked={f.acks.includes(code)}
                onChange={(e) => setF((x) => ({ ...x, acks: e.target.checked ? [...x.acks, code] : x.acks.filter((a) => a !== code) }))} />
              <CodeLabel prefix={STANDARD_ACKS.includes(code) ? "ack." : "rule."} code={code} />
            </label>
          ))}
        </div>
      </fieldset>
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
          <h1>{p?.title ?? t2("fu.title", { code: "" })}</h1>
          <p className="muted"><span className="mono xs">{p?.code ?? ""}</span>{p?.code ? " · " : ""}{t2("fu.lead")}</p>
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
                <ul className="small">{list.slice(1).map((o) => <li key={o.id}><OutcomeBadge status={o.status} /> {dateTime(o.created_at, lang)} · v{o.dataset_version}{o.interim ? ` · ${t2("fu.interim_short")}` : ""}</li>)}</ul>
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
                    {c.evidence_entry && <Badge tone={c.evidence_entry.review_status === "accepted" ? "ok" : "neutral"}><CodeLabel prefix="iv.review." code={String(c.evidence_entry.review_status)} /></Badge>}
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
