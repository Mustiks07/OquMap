import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useCurriculum } from "../../api/hooks";
import { useAppState } from "../../state/AppState";
import { Alert, Badge, Button, Card, Field, Select } from "../../ui";
import { dateTime } from "../../ui/format";
import {
  useIntervention, useInterventions, useMAction, useSuggestions, type InterventionCreate, type InterventionOut,
  type InterventionVersionOut,
} from "../measurement/api";
import { ActionError, KV, MQuery, Messages, OutcomeBadge, FidelityBadge, VersionStatusBadge, useRoles } from "../measurement/components";
import { useMT } from "../measurement/i18n";

const MISCONCEPTIONS = ["add_across", "numerators_not_scaled", "subtract_across", "multiplied_instead", "mixed_subtract_reverse",
  "borrow_error", "whole_part_error", "answered_complement", "wrong_operation", "incomplete_simplification"];

type Target = { target_type: "topic" | "objective" | "misconception"; target_id?: string | null; misconception_code?: string | null };

function TargetEditor({ targets, onChange }: { targets: Target[]; onChange: (t: Target[]) => void }) {
  const { t2, pick } = useMT();
  const cur = useCurriculum();
  const [type, setType] = useState<Target["target_type"]>("topic");
  const [value, setValue] = useState("");
  const options = type === "topic" ? (cur.data?.topics ?? []).map((x) => ({ value: x.id, label: `${x.code} ${pick(x, "title")}` }))
    : type === "objective" ? (cur.data?.objectives ?? []).map((x) => ({ value: x.id, label: `${x.code} ${pick(x, "text")}` }))
      : MISCONCEPTIONS.map((c) => ({ value: c, label: c }));
  const labelOf = (tg: Target) => {
    if (tg.target_type === "misconception") return tg.misconception_code;
    const list = tg.target_type === "topic" ? cur.data?.topics : cur.data?.objectives;
    return list?.find((x) => x.id === tg.target_id)?.code ?? tg.target_id;
  };
  return (
    <div className="stack">
      <ul className="row" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {targets.map((tg, i) => (
          <li key={i}>
            <Badge tone="info">{t2(`iv.target.${tg.target_type}`)}: {labelOf(tg)}</Badge>{" "}
            <button type="button" className="btn btn-ghost btn-sm" aria-label={`× ${labelOf(tg)}`} onClick={() => onChange(targets.filter((_, j) => j !== i))}>×</button>
          </li>
        ))}
      </ul>
      <div className="row">
        <Select ariaLabel={t2("iv.targets")} value={type} onChange={(v) => { setType(v as Target["target_type"]); setValue(""); }}
          options={(["topic", "objective", "misconception"] as const).map((x) => ({ value: x, label: t2(`iv.target.${x}`) }))} />
        <Select ariaLabel={t2(`iv.target.${type}`)} value={value} onChange={setValue} options={[{ value: "", label: "—" }, ...options]} />
        <Button size="sm" disabled={!value} onClick={() => {
          onChange([...targets, type === "misconception" ? { target_type: type, misconception_code: value } : { target_type: type, target_id: value }]);
          setValue("");
        }}>{t2("iv.add_target")}</Button>
      </div>
    </div>
  );
}

const EMPTY: InterventionCreate = {
  code: "", title_ru: "", title_kz: "", description_ru: "", description_kz: "", grades: [6], languages: ["ru"], minutes_per_session: 20,
  sessions_per_week: 2, duration_weeks: 4, cadence_ru: "", instructions_ru: "", instructions_kz: "", resources: [], evidence_level: "practice_based",
  evidence_links: [], contraindications_ru: "", limitations_ru: "", limitations_kz: "", targets: [],
};

export function InterventionForm({ initial, mode, onDone, onCancel }: {
  initial?: InterventionVersionOut; mode: "create" | "edit" | "new_version"; onDone: (iv: InterventionOut) => void; onCancel: () => void;
}) {
  const { t2, t } = useMT();
  const { datasetId } = useAppState();
  const params = useParams();
  const [f, setF] = useState<InterventionCreate>(() => initial ? {
    ...EMPTY, ...(initial as unknown as InterventionCreate), code: "",
    targets: initial.targets.map((x) => ({ target_type: x.target_type as Target["target_type"], target_id: x.target_id, misconception_code: x.misconception_code })),
  } : { ...EMPTY });
  const [note, setNote] = useState("");
  const set = <K extends keyof InterventionCreate>(k: K, v: InterventionCreate[K]) => setF((x) => ({ ...x, [k]: v }));
  const create = useMAction<InterventionCreate, InterventionOut>("POST", () => "/api/v1/interventions");
  const patch = useMAction<Partial<InterventionCreate>, InterventionOut>("PATCH", () => `/api/v1/interventions/${params.id}`);
  const version = useMAction<Partial<InterventionCreate> & { change_note: string }, InterventionOut>("POST", () => `/api/v1/interventions/${params.id}/versions`);
  const busy = create.isPending || patch.isPending || version.isPending;
  const err = create.error || patch.error || version.error;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const { code, ...content } = f;
    const res = mode === "create" ? await create.mutateAsync({ ...f, dataset_id: datasetId ?? null } as InterventionCreate)
      : mode === "edit" ? await patch.mutateAsync({ ...content, expected_version: initial?.version } as Partial<InterventionCreate>)
        : await version.mutateAsync({ ...content, change_note: note });
    void code;
    onDone(res);
  }
  const txt = (k: keyof InterventionCreate, label: string, area = false) => (
    <Field label={label}>
      {(id) => area
        ? <textarea id={id} className="input" value={(f[k] as string) ?? ""} onChange={(e) => set(k, e.target.value as never)} />
        : <input id={id} className="input" value={(f[k] as string) ?? ""} onChange={(e) => set(k, e.target.value as never)} />}
    </Field>
  );
  const nums = (k: "minutes_per_session" | "sessions_per_week" | "duration_weeks", label: string) => (
    <Field label={label}>{(id) => <input id={id} className="input input-num" type="number" min={1} value={f[k] ?? 1} onChange={(e) => set(k, Number(e.target.value))} />}</Field>
  );
  return (
    <form className="stack" onSubmit={submit} aria-label={t2("iv.new")}>
      {mode === "create" && txt("code", t2("iv.code"))}
      <div className="grid grid-2">{txt("title_ru", `${t2("iv.name")} (RU)`)}{txt("title_kz", `${t2("iv.name")} (KZ)`)}</div>
      {txt("description_ru", t2("iv.description"), true)}
      {txt("instructions_ru", t2("iv.instructions"), true)}
      <div className="grid grid-3">{nums("minutes_per_session", t2("iv.minutes"))}{nums("sessions_per_week", t2("iv.per_week"))}{nums("duration_weeks", t2("iv.weeks"))}</div>
      <div className="grid grid-3">
        <Field label={t2("iv.evidence")}>
          {(id) => <Select id={id} value={f.evidence_level ?? "practice_based"} onChange={(v) => set("evidence_level", v as InterventionCreate["evidence_level"])}
            options={(["practice_based", "observational", "experimental"] as const).map((x) => ({ value: x, label: t2(`iv.level.${x}`) }))} />}
        </Field>
        <Field label={t2("iv.grades")}>{(id) => <input id={id} className="input" value={(f.grades ?? []).join(", ")}
          onChange={(e) => set("grades", e.target.value.split(",").map((x) => Number(x.trim())).filter((x) => Number.isFinite(x) && x > 0))} />}</Field>
        <Field label={t2("iv.languages")}>{(id) => <input id={id} className="input" value={(f.languages ?? []).join(", ")}
          onChange={(e) => set("languages", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} />}</Field>
      </div>
      {txt("contraindications_ru", t2("iv.contra"), true)}
      {txt("limitations_ru", t2("iv.limitations"), true)}
      <Field label={t2("iv.resources")}>{(id) => <input id={id} className="input" value={(f.resources ?? []).join("; ")}
        onChange={(e) => set("resources", e.target.value.split(";").map((x) => x.trim()).filter(Boolean))} />}</Field>
      <fieldset className="stack" style={{ border: "1px solid var(--color-border)", borderRadius: 8, padding: 12 }}>
        <legend className="small">{t2("iv.targets")}</legend>
        <TargetEditor targets={(f.targets ?? []) as Target[]} onChange={(tg) => set("targets", tg as InterventionCreate["targets"])} />
      </fieldset>
      {mode === "new_version" && <Field label={t2("iv.change_note")}>{(id) => <input id={id} className="input" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>}
      <ActionError error={err} />
      <div className="row">
        <Button type="submit" variant="primary" disabled={busy || !f.title_ru || (mode === "create" && !f.code)}>{t2("common.save")}</Button>
        <Button onClick={onCancel}>{t("common.cancel")}</Button>
      </div>
    </form>
  );
}

function SuggestPanel({ topicId, misconception }: { topicId?: string; misconception?: string }) {
  const { t2, pick } = useMT();
  const { datasetId } = useAppState();
  const q = useSuggestions(topicId || misconception ? { dataset_id: datasetId ?? undefined, topic_id: topicId, misconception } : null);
  return (
    <Card title={t2("iv.suggest_title")} id="suggest">
      <p className="small muted">{t2("iv.suggest_lead")}</p>
      <MQuery q={q} empty={(d) => d.suggestions.length === 0}>
        {(d) => (
          <div className="stack">
            <ol className="stack" style={{ margin: 0, paddingLeft: 18 }} data-testid="suggestions">
              {d.suggestions.map((s) => (
                <li key={s.intervention_id}>
                  <Link to={`/interventions/${s.intervention_id}`}><strong>{pick(s, "title")}</strong></Link> <span className="mono xs">{s.code} v{s.version}</span>{" "}
                  <Badge tone="info">{t2("iv.score")}: {s.score}</Badge>
                  <div className="xs muted">{s.components.map((c) => `${c.code} +${c.points}`).join(" · ")}</div>
                </li>
              ))}
            </ol>
            {d.excluded.length > 0 && <p className="xs muted">{t2("iv.excluded")}: {d.excluded.map((e) => `${e.code} (${e.reason})`).join(", ")}</p>}
            <Messages items={d.limitations} />
          </div>
        )}
      </MQuery>
    </Card>
  );
}

export function InterventionsPage() {
  const { t2, pick } = useMT();
  const [sp] = useSearchParams();
  const cur = useCurriculum();
  const { canDraft } = useRoles();
  const { datasetId } = useAppState();
  const nav = useNavigate();
  const [filters, setFilters] = useState({ status: "", evidence_level: "", q: "" });
  const [creating, setCreating] = useState(false);
  const q = useInterventions({ status: filters.status || undefined, evidence_level: filters.evidence_level || undefined, q: filters.q || undefined });
  const topicCode = sp.get("topic_code");
  const suggestTopic = useMemo(() => cur.data?.topics.find((x) => x.code === topicCode)?.id, [cur.data, topicCode]);
  const suggest = sp.get("suggest") === "1";
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t2("iv.title")}</h1>
          <p className="muted">{t2("iv.lead")}</p>
        </div>
        {canDraft && <Button variant="primary" onClick={() => setCreating(true)} disabled={creating}>{t2("iv.new")}</Button>}
      </div>
      {suggest && <SuggestPanel topicId={suggestTopic} misconception={sp.get("misconception") ?? undefined} />}
      {creating && (
        <Card title={t2("iv.new")}>
          {!datasetId && <Alert tone="info">{t2("common.current_dataset")}: —</Alert>}
          <InterventionForm mode="create" onCancel={() => setCreating(false)} onDone={(iv) => nav(`/interventions/${iv.id}`)} />
        </Card>
      )}
      <div className="row" role="search">
        <Field label={t2("common.search")}>{(id) => <input id={id} className="input" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />}</Field>
        <Field label={t2("common.status")}>{(id) => <Select id={id} value={filters.status} onChange={(v) => setFilters({ ...filters, status: v })}
          options={[{ value: "", label: t2("common.all") }, { value: "active", label: "active" }, { value: "archived", label: t2("iv.archived") }]} />}</Field>
        <Field label={t2("iv.evidence")}>{(id) => <Select id={id} value={filters.evidence_level} onChange={(v) => setFilters({ ...filters, evidence_level: v })}
          options={[{ value: "", label: t2("common.all") }, ...(["practice_based", "observational", "experimental"] as const).map((x) => ({ value: x, label: t2(`iv.level.${x}`) }))]} />}</Field>
      </div>
      <MQuery q={q} empty={(d) => d.length === 0}>
        {(rows) => (
          <div className="table-wrap">
            <table className="table" data-testid="interventions">
              <caption className="sr-only">{t2("iv.title")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t2("iv.code")}</th><th scope="col">{t2("iv.name")}</th><th scope="col">{t2("common.version")}</th>
                  <th scope="col">{t2("iv.evidence")}</th><th scope="col">{t2("iv.targets")}</th><th scope="col" className="num">{t2("iv.dosage")}</th>
                  <th scope="col" className="num">{t2("iv.pilots")}</th><th scope="col" className="num">{t2("iv.accepted")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => nav(`/interventions/${r.id}`)}>
                    <td className="mono"><Link to={`/interventions/${r.id}`} onClick={(e) => e.stopPropagation()}>{r.code}</Link></td>
                    <td>{pick(r, "title")} {r.status === "archived" && <Badge tone="warn">{t2("iv.archived")}</Badge>}</td>
                    <td>v{r.latest_version} <VersionStatusBadge status={r.current_status} />{r.reviewed_version && r.reviewed_version !== r.latest_version ? <span className="xs muted"> (v{r.reviewed_version} ✓)</span> : null}</td>
                    <td>{t2(`iv.level.${r.evidence_level}`)}</td>
                    <td className="xs">{r.targets.map((x) => x.code).join(", ")}</td>
                    <td className="num xs">{t2("iv.minutes_total", { total: r.total_minutes })}</td>
                    <td className="num">{r.n_pilots}</td>
                    <td className="num">{r.accepted_evidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </MQuery>
    </div>
  );
}

function VersionView({ v }: { v: InterventionVersionOut }) {
  const { t2, lang, pick } = useMT();
  return (
    <div className="stack">
      <div className="row"><strong>v{v.version}</strong> <VersionStatusBadge status={v.status} />
        <span className="xs muted">{dateTime(v.created_at, lang)} · {v.author ?? "—"}{v.reviewed_by ? ` · ✓ ${v.reviewed_by} ${dateTime(v.reviewed_at, lang)}` : ""}</span>
      </div>
      {v.change_note && <p className="small" style={{ margin: 0 }}>{t2("iv.change_note")}: {v.change_note}</p>}
      <p style={{ margin: 0 }}>{pick(v, "description")}</p>
      <KV rows={[
        [t2("iv.dosage"), `${v.minutes_per_session} × ${v.sessions_per_week} × ${v.duration_weeks} = ${t2("iv.minutes_total", { total: v.total_minutes })}${v.cadence_ru ? ` (${v.cadence_ru})` : ""}`],
        [t2("iv.evidence"), t2(`iv.level.${v.evidence_level}`)],
        [t2("iv.targets"), v.targets.map((x) => `${x.code} — ${lang === "kz" ? x.label_kz : x.label_ru}`).join("; ") || "—"],
        ["Классы / языки", `${v.grades.join(", ") || "—"} / ${v.languages.join(", ") || "—"}`],
        [t2("iv.instructions"), <span key="i" style={{ whiteSpace: "pre-wrap" }}>{pick(v, "instructions") || "—"}</span>],
        [t2("iv.resources"), v.resources.join("; ") || "—"],
        [t2("iv.evidence_links"), v.evidence_links.length ? v.evidence_links.map((l) => `${String(l.title)}${l.url ? ` (${String(l.url)})` : ""}`).join("; ") : "—"],
        [t2("iv.contra"), v.contraindications_ru || "—"],
        [t2("iv.limitations"), pick(v, "limitations") || "—"],
        [t2("iv.sha"), <code key="s" className="xs">{v.content_sha256.slice(0, 16)}…</code>],
        ["", <span key="u" className="xs muted">{t2("iv.used_by", { n: v.used_by_pilots })}</span>],
      ]} />
    </div>
  );
}

export function InterventionDetailPage() {
  const { id } = useParams();
  const { t2, pick } = useMT();
  const q = useIntervention(id);
  const nav = useNavigate();
  const { canDraft, canApprove } = useRoles();
  const [mode, setMode] = useState<"" | "edit" | "new_version" | "archive">("");
  const [reason, setReason] = useState("");
  const review = useMAction<{ version: number }, InterventionOut>("POST", (b) => `/api/v1/interventions/${id}/versions/${b.version}/review`, () => ({ note: "" }));
  const archive = useMAction<{ reason: string }, InterventionOut>("POST", () => `/api/v1/interventions/${id}/archive`);
  const del = useMAction<{ version: number }, unknown>("DELETE", (b) => `/api/v1/interventions/${id}/versions/${b.version}`);
  const evReview = useMAction<{ entry: string; accept: boolean }, unknown>("POST", (b) => `/api/v1/intervention-evidence/${b.entry}/review`, (b) => ({ accept: b.accept, note: "" }));
  return (
    <div className="page stack">
      <MQuery q={q}>
        {(iv) => {
          const cur = iv.current;
          const draft = cur.status === "draft" && iv.status !== "archived";
          return (
            <>
              <div className="page-header">
                <div>
                  <h1>{pick(cur, "title")}</h1>
                  <p className="muted small"><span className="mono">{iv.code}</span> · v{iv.latest_version} <VersionStatusBadge status={cur.status} />
                    {iv.status === "archived" && <> · <Badge tone="warn">{t2("iv.archived")}</Badge> {iv.archived_reason}</>}</p>
                </div>
                <div className="row">
                  <Button onClick={() => nav("/interventions")}>{t2("common.back")}</Button>
                  {iv.status !== "archived" && iv.reviewed_version && canDraft && (
                    <Button variant="primary" onClick={() => nav(`/pilots/new?intervention=${iv.id}`)}>{t2("iv.start_pilot")}</Button>
                  )}
                </div>
              </div>
              {!draft && iv.status !== "archived" && <Alert tone="info">{t2("iv.immutable")}</Alert>}
              <div className="row" role="group" aria-label={t2("common.actions")}>
                {draft && canDraft && <Button onClick={() => setMode("edit")}>{t2("iv.edit_draft")}</Button>}
                {draft && canApprove && <Button variant="primary" disabled={review.isPending} onClick={() => review.mutate({ version: cur.version })}>{t2("iv.review")}</Button>}
                {draft && canDraft && cur.used_by_pilots === 0 && (
                  <Button variant="danger" onClick={() => del.mutate({ version: cur.version }, { onSuccess: (r) => { if ((r as { intervention_deleted: boolean }).intervention_deleted) nav("/interventions"); } })}>
                    {t2("iv.delete_draft")}
                  </Button>
                )}
                {!draft && iv.status !== "archived" && canDraft && <Button onClick={() => setMode("new_version")}>{t2("iv.new_version")}</Button>}
                {iv.status !== "archived" && canApprove && <Button variant="danger" onClick={() => setMode("archive")}>{t2("iv.archive")}</Button>}
              </div>
              <ActionError error={review.error || archive.error || del.error || evReview.error} />
              {mode === "archive" && (
                <Card>
                  <Field label={t2("iv.archive_reason")}>{(fid) => <input id={fid} className="input" value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
                  <div className="row" style={{ marginTop: 8 }}>
                    <Button variant="danger" disabled={reason.trim().length < 3} onClick={() => archive.mutate({ reason }, { onSuccess: () => setMode("") })}>{t2("iv.archive")}</Button>
                    <Button onClick={() => setMode("")}>{t2("common.cancel")}</Button>
                  </div>
                </Card>
              )}
              {(mode === "edit" || mode === "new_version") && (
                <Card title={mode === "edit" ? t2("iv.edit_draft") : t2("iv.new_version")}>
                  <InterventionForm mode={mode} initial={cur} onCancel={() => setMode("")} onDone={() => setMode("")} />
                </Card>
              )}
              <div className="grid" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
                <Card title={`${t2("common.version")} ${cur.version}`}><VersionView v={cur} /></Card>
                <Card title={t2("iv.evidence_summary")}>
                  <p className="xs muted">{t2("iv.evidence_note")}</p>
                  <KV rows={[[t2("iv.accepted"), iv.evidence_summary.accepted_entries], ["proposed", iv.evidence_summary.proposed_entries],
                    ["repeated", iv.evidence_summary.repeated_positive_signal ? t2("common.yes") : t2("common.none")]]} />
                  <ul className="stack" style={{ listStyle: "none", padding: 0, marginTop: 8 }}>
                    {iv.evidence_summary.entries.map((e) => (
                      <li key={String(e.id)} className="small">
                        <OutcomeBadge status={String(e.outcome_status)} /> <FidelityBadge code={String(e.fidelity_class)} /> <span className="xs">v{String(e.intervention_version)} · {String(e.design)} · {String(e.review_status)}</span>
                        <Link to={`/pilots/${String(e.pilot_id)}/follow-up`} className="xs"> → {t2("pilot.followup")}</Link>
                        {e.review_status === "proposed" && canApprove && (
                          <span className="row" style={{ gap: 4 }}>
                            <Button size="sm" onClick={() => evReview.mutate({ entry: String(e.id), accept: true })}>{t2("fu.accept")}</Button>
                            <Button size="sm" onClick={() => evReview.mutate({ entry: String(e.id), accept: false })}>{t2("fu.reject")}</Button>
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </Card>
              </div>
              <Card title={t2("iv.versions")}>
                <ol className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {iv.versions.filter((v) => v.version !== cur.version).map((v) => <li key={v.id} style={{ borderTop: "1px solid var(--color-border)", paddingTop: 8 }}><VersionView v={v} /></li>)}
                </ol>
                {iv.versions.length === 1 && <p className="small muted">—</p>}
              </Card>
            </>
          );
        }}
      </MQuery>
    </div>
  );
}
