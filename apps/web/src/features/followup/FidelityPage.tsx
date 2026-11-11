import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Alert, Badge, Button, Card, Field, Metric, Select } from "../../ui";
import { dateTime } from "../../ui/format";
import { useFidelity, useMAction, usePilot, type FidelityLogCreate, type FidelityLogOut, type FidelityMetrics } from "../measurement/api";
import { ActionError, CodeLabel, FidelityBadge, MQuery, Messages, Num, Share, useRoles } from "../measurement/components";
import { useMT } from "../measurement/i18n";

function MetricsRow({ m }: { m: FidelityMetrics }) {
  const { t2 } = useMT();
  return (
    <div className="grid grid-4">
      <Metric label={t2("fid.expected")} value={<Num v={m.expected_sessions} />} sub={`${t2("fid.logged")}: ${m.logged_sessions} · ${t2("fid.missing")}: ${m.missing_logs}`} />
      <Metric label={t2("fid.dosage")} value={<Share v={m.dosage_completion} />} sub={`${t2("fid.sessions")}: ${m.delivered_sessions} / ${m.expected_sessions}`} />
      <Metric label={t2("fid.reach")} value={<Share v={m.reach} />} sub={`${t2("fid.coverage")}: ${m.log_coverage == null ? "—" : Math.round(m.log_coverage * 100) + "%"}`} />
      <Metric label={t2("fid.adherence")} value={<Share v={m.adherence} />} sub={`${t2("fid.cancelled")}: ${m.cancelled_sessions}`} />
    </div>
  );
}

const DISRUPTIONS = ["none", "cancelled", "shortened", "teacher_absent", "holiday", "other"] as const;
const SOURCES = ["teacher_log", "observation", "coach_visit", "import"] as const;
const CHECKLIST = [{ key: "model", label: "Модель показана" }, { key: "practice", label: "Самостоятельная практика" }, { key: "check", label: "Проверка по чек-листу" }];

function LogForm({ pilotId, cohorts, minutes, correcting, onDone }: {
  pilotId: string; cohorts: { cohort_id: string; code: string | null; n_learners: number | null }[]; minutes: number;
  correcting?: FidelityLogOut | null; onDone: () => void;
}) {
  const { t2 } = useMT();
  const base = correcting ?? null;
  const [f, setF] = useState({
    cohort_id: base?.cohort_id ?? cohorts[0]?.cohort_id ?? "", session_date: base?.session_date ?? "", planned_minutes: base?.planned_minutes ?? minutes,
    delivered_minutes: base?.delivered_minutes ?? minutes, activities_planned: base?.activities_planned ?? 3, activities_completed: base?.activities_completed ?? 3,
    learners_present: base?.learners_present ?? null as number | null, learners_assigned: base?.learners_assigned ?? (cohorts[0]?.n_learners ?? null) as number | null,
    adaptation_note: base?.adaptation_note ?? "", disruption: (base?.disruption ?? "none") as FidelityLogCreate["disruption"],
    disruption_note: base?.disruption_note ?? "", source: (base?.source ?? "teacher_log") as FidelityLogCreate["source"],
  });
  const [checks, setChecks] = useState<Record<string, boolean>>(() => Object.fromEntries(CHECKLIST.map((c) => [c.key, base ? !!base.adherence.find((a) => a.key === c.key && a.done) : true])));
  const add = useMAction<FidelityLogCreate, FidelityLogOut>("POST", () => `/api/v1/pilots/${pilotId}/fidelity-logs`);
  const set = (k: keyof typeof f, v: unknown) => setF((x) => ({ ...x, [k]: v }));
  const numInp = (k: keyof typeof f, label: string) => (
    <Field label={label}>{(id) => <input id={id} className="input input-num" type="number" min={0} value={(f[k] as number | null) ?? ""}
      onChange={(e) => set(k, e.target.value === "" ? null : Number(e.target.value))} />}</Field>
  );
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await add.mutateAsync({ ...f, completed_tasks: [], adherence: CHECKLIST.map((c) => ({ ...c, done: !!checks[c.key] })), corrects_log_id: correcting?.id ?? null });
    onDone();
  }
  return (
    <form className="stack" onSubmit={submit} aria-label={t2("fid.add")}>
      {correcting && <Alert tone="info">{t2("fid.correction_of")} {correcting.session_date} ({correcting.cohort_code})</Alert>}
      <div className="grid grid-3">
        <Field label={t2("fid.cohort")}>{(id) => <Select id={id} value={f.cohort_id} onChange={(v) => set("cohort_id", v)}
          options={cohorts.map((c) => ({ value: c.cohort_id, label: c.code ?? c.cohort_id }))} />}</Field>
        <Field label={t2("fid.date")}>{(id) => <input id={id} className="input" type="date" required value={f.session_date} onChange={(e) => set("session_date", e.target.value)} />}</Field>
        <Field label={t2("fid.source")}>{(id) => <Select id={id} value={f.source} onChange={(v) => set("source", v)} options={SOURCES.map((s) => ({ value: s, label: t2(`fid.src.${s}`) }))} />}</Field>
      </div>
      <div className="grid grid-4">
        {numInp("planned_minutes", t2("fid.planned_min"))}{numInp("delivered_minutes", t2("fid.delivered_min"))}
        {numInp("activities_planned", t2("fid.act_planned"))}{numInp("activities_completed", t2("fid.act_done"))}
      </div>
      <div className="grid grid-3">
        {numInp("learners_present", t2("fid.present"))}{numInp("learners_assigned", t2("fid.assigned"))}
        <Field label={t2("fid.disruption")}>{(id) => <Select id={id} value={f.disruption} onChange={(v) => { set("disruption", v); if (v === "cancelled") set("delivered_minutes", 0); }}
          options={DISRUPTIONS.map((d) => ({ value: d, label: t2(`fid.dis.${d}`) }))} />}</Field>
      </div>
      <fieldset style={{ border: "1px solid var(--color-border)", borderRadius: 8, padding: 12 }}>
        <legend className="small">{t2("fid.checklist")}</legend>
        <div className="row">
          {CHECKLIST.map((c) => (
            <label key={c.key} className="row small" style={{ gap: 6 }}>
              <input type="checkbox" checked={!!checks[c.key]} onChange={(e) => setChecks((x) => ({ ...x, [c.key]: e.target.checked }))} /> {c.label}
            </label>
          ))}
        </div>
      </fieldset>
      <Field label={t2("fid.adaptation")}>{(id) => <textarea id={id} className="input" maxLength={2000} value={f.adaptation_note} onChange={(e) => set("adaptation_note", e.target.value)} />}</Field>
      <ActionError error={add.error} />
      <div className="row">
        <Button type="submit" variant="primary" disabled={add.isPending || !f.session_date}>{t2("common.save")}</Button>
        <Button onClick={onDone}>{t2("common.cancel")}</Button>
      </div>
    </form>
  );
}

export function FidelityPage() {
  const { id } = useParams();
  const { t2, lang } = useMT();
  const pilot = usePilot(id);
  const q = useFidelity(id);
  const nav = useNavigate();
  const { canLog } = useRoles();
  const [form, setForm] = useState<false | "new" | FidelityLogOut>(false);
  const running = pilot.data?.status === "active" || pilot.data?.status === "completed";
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t2("fid.title", { code: pilot.data?.code ?? "" })}</h1>
          <p className="muted">{t2("fid.lead")}</p>
        </div>
        <div className="row">
          <Button onClick={() => nav(`/pilots/${id}`)}>{t2("common.back")}</Button>
          {canLog && running && <Button variant="primary" onClick={() => setForm("new")}>{t2("fid.add")}</Button>}
        </div>
      </div>
      {form && pilot.data && (
        <Card title={t2("fid.add")}>
          <LogForm pilotId={pilot.data.id} minutes={pilot.data.planned.minutes_per_session} correcting={form === "new" ? null : form}
            cohorts={pilot.data.cohorts.filter((c) => c.arm === "intervention")} onDone={() => setForm(false)} />
        </Card>
      )}
      <MQuery q={q}>
        {(d) => (
          <>
            <Card title={t2("fid.overall")} actions={<FidelityBadge code={d.overall.classification.code} />}>
              <MetricsRow m={d.overall} />
              <p className="xs muted" style={{ marginTop: 8 }}>{t2("fid.rules")} · {d.method_version} · {t2("common.as_of", { date: d.as_of })} · {t2("fid.expected_from")}: {t2(`fid.expected_source.${d.expected_source}`)} ·{" "}
                {d.overall.reasons.map((c, i) => <span key={c}>{i > 0 && ", "}<CodeLabel prefix="fid.reason." code={c} /></span>)}</p>
              <div className="row">{Object.entries(d.distribution).map(([k, v]) => <span key={k}><FidelityBadge code={k} /> {v}</span>)}</div>
            </Card>
            <Messages items={d.limitations} />
            {!d.cohort_detail_visible ? null : (
              <>
                <Card title={t2("fid.by_cohort")}>
                  <div className="table-wrap">
                    <table className="table" data-testid="fidelity-cohorts">
                      <caption className="sr-only">{t2("fid.by_cohort")}</caption>
                      <thead><tr>
                        <th scope="col">{t2("fid.cohort")}</th><th scope="col" className="num">{t2("fid.logged")} / {t2("fid.expected")}</th>
                        <th scope="col" className="num">{t2("fid.dosage")}</th><th scope="col" className="num">{t2("fid.sessions")}</th>
                        <th scope="col" className="num">{t2("fid.reach")}</th><th scope="col" className="num">{t2("fid.adherence")}</th><th scope="col">{t2("common.status")}</th>
                      </tr></thead>
                      <tbody>
                        {(d.cohorts ?? []).map((c) => (
                          <tr key={c.cohort_id}>
                            <td className="mono">{c.code}</td>
                            <td className="num">{c.metrics.logged_sessions} / {c.metrics.expected_sessions}</td>
                            <td className="num"><Share v={c.metrics.dosage_completion} /></td>
                            <td className="num"><Share v={c.metrics.session_completion} /></td>
                            <td className="num"><Share v={c.metrics.reach} /></td>
                            <td className="num"><Share v={c.metrics.adherence} /></td>
                            <td><FidelityBadge code={c.metrics.classification.code} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
                <Card title={t2("fid.logs")}>
                  <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
                    <table className="table">
                      <caption className="sr-only">{t2("fid.logs")}</caption>
                      <thead><tr>
                        <th scope="col">{t2("fid.date")}</th><th scope="col">{t2("fid.cohort")}</th><th scope="col" className="num">{t2("fid.delivered_min")}</th>
                        <th scope="col">{t2("fid.disruption")}</th><th scope="col">{t2("fid.adaptation")}</th><th scope="col">{t2("fid.recorder")}</th><th scope="col" />
                      </tr></thead>
                      <tbody>
                        {(d.logs ?? []).map((l) => (
                          <tr key={l.id} style={l.superseded_by ? { opacity: 0.55 } : undefined}>
                            <td className="mono">{l.session_date}</td><td className="mono">{l.cohort_code}</td>
                            <td className="num">{l.delivered_minutes} / {l.planned_minutes}</td>
                            <td>{t2(`fid.dis.${l.disruption}`)}{l.corrects_log_id && <Badge tone="info">{t2("fid.correction_of")}</Badge>}{l.superseded_by && <Badge tone="neutral">{t2("fid.superseded")}</Badge>}</td>
                            <td className="small">{l.adaptation_note || l.disruption_note || "—"}</td>
                            <td className="xs">{l.recorder ?? "—"} · {dateTime(l.created_at, lang)} · {t2(`fid.src.${l.source}`)}</td>
                            <td>{canLog && running && !l.superseded_by && <Button size="sm" onClick={() => setForm(l)}>{t2("fid.correct")}</Button>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </>
            )}
          </>
        )}
      </MQuery>
    </div>
  );
}
