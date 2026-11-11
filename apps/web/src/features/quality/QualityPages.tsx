import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAppState } from "../../state/AppState";
import { Alert, Badge, Button, Card, Field, Metric, Select, StaleBanner } from "../../ui";
import { dateTime } from "../../ui/format";
import { useAssessmentQuality, useAssignments, useDif, useItemQuality, useMAction, useQualityList, type ItemQuality, type QualityRules } from "../measurement/api";
import { ActionError, CodeLabel, KV, MQuery, Messages, Num, Pager, Share, Stat, useRoles, useUrlState } from "../measurement/components";
import { useMT } from "../measurement/i18n";

function RulesBar({ rules, onChange }: { rules: QualityRules; onChange: (r: QualityRules) => void }) {
  const { t2 } = useMT();
  return (
    <div className="row" role="group" aria-label={t2("common.filter")}>
      <Field label={t2("quality.attempt_rule")}>
        {(id) => (
          <Select id={id} value={rules.attempt_rule} onChange={(v) => onChange({ ...rules, attempt_rule: v as QualityRules["attempt_rule"] })}
            options={[{ value: "first", label: t2("quality.first") }, { value: "last", label: t2("quality.last") }]} />
        )}
      </Field>
      <Field label={t2("quality.omitted_policy")}>
        {(id) => (
          <Select id={id} value={rules.omitted_policy} onChange={(v) => onChange({ ...rules, omitted_policy: v as QualityRules["omitted_policy"] })}
            options={[{ value: "as_incorrect", label: t2("quality.as_incorrect") }, { value: "exclude", label: t2("quality.exclude") }]} />
        )}
      </Field>
    </div>
  );
}

const PAGE = 25;

export function QualityListPage() {
  const { t2, lang, pick } = useMT();
  const { datasetId } = useAppState();
  const [u, setU] = useUrlState({ scope: datasetId ? "current" : "all", attempt_rule: "first", omitted_policy: "as_incorrect", offset: "0" });
  const scope = u.scope as "current" | "all";
  const rules: QualityRules = { attempt_rule: u.attempt_rule as QualityRules["attempt_rule"], omitted_policy: u.omitted_policy as QualityRules["omitted_policy"] };
  const offset = Number(u.offset) || 0;
  const q = useQualityList(scope === "current" ? datasetId : null, rules, PAGE, offset);
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t2("quality.title")}</h1>
          <p className="muted">{t2("quality.lead")}</p>
        </div>
      </div>
      <div className="row">
        <Field label={t2("common.dataset")}>
          {(id) => (
            <Select id={id} value={scope} onChange={(v) => setU({ scope: v, offset: "0" })}
              options={[...(datasetId ? [{ value: "current", label: t2("common.current_dataset") }] : []), { value: "all", label: t2("common.all_datasets") }]} />
          )}
        </Field>
        <RulesBar rules={rules} onChange={(r) => setU({ ...r, offset: "0" })} />
      </div>
      <MQuery q={q} empty={(d) => d.assessments.length === 0}>
        {(d) => (
          <div className="table-wrap">
            <table className="table" data-testid="quality-list">
              <caption className="sr-only">{t2("quality.title")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t2("quality.assessment")}</th>
                  <th scope="col">{t2("common.dataset")}</th>
                  <th scope="col">{t2("quality.form")}</th>
                  <th scope="col" className="num">{t2("quality.present")}</th>
                  <th scope="col" className="num">{t2("quality.omission")}</th>
                  <th scope="col" className="num">{t2("quality.mean")}</th>
                  <th scope="col" className="num">{t2("quality.alpha")}</th>
                  <th scope="col" className="num">{t2("quality.flagged")}</th>
                </tr>
              </thead>
              <tbody>
                {d.assessments.map((a) => (
                  <tr key={a.assessment.assessment_id}>
                    <th scope="row">
                      <Link to={`/quality/${a.assessment.assessment_id}`} className="mono"
                        aria-label={`${t2("quality.assessment")} ${a.assessment.code}: ${a.assessment.form_code}`}>{a.assessment.code}</Link>
                      <div className="xs muted">{a.assessment.stage} · {a.assessment.administered_on ?? "—"}</div>
                      {!a.denominators.assigned_is_exact && <div className="xs muted">{t2("quality.scope.inferred_from_sittings")}</div>}
                    </th>
                    <td className="small">{pick(a.dataset, "name")}</td>
                    <td className="mono small">{a.assessment.form_code} / {a.assessment.scale_code}</td>
                    <td className="num"><Num v={a.denominators.present} /> / <Num v={a.denominators.assigned} /></td>
                    <td className="num"><Share v={a.omission_rate} /></td>
                    <td className="num"><Share v={a.mean_score} /></td>
                    <td className="num"><Stat value={a.cronbach_alpha.value} reason={a.cronbach_alpha.unavailable_reason} /></td>
                    <td className="num">{a.n_flagged_items > 0 ? <Badge tone="warn">{a.n_flagged_items}</Badge> : <Badge tone="ok">0</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="xs muted" style={{ padding: 8 }}>{d.method_version} · {dateTime(d.assessments[0]?.generated_at, lang)}</p>
            <Pager total={d.total} limit={d.limit} offset={d.offset} onChange={(o) => setU({ offset: String(o) })} />
          </div>
        )}
      </MQuery>
    </div>
  );
}

function Histogram({ bins }: { bins: { from: number; to: number; count: number }[] }) {
  const { t2 } = useMT();
  const max = Math.max(1, ...bins.map((b) => b.count));
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${bins.length * 24} 80`} width="100%" height="90" role="img" aria-label={t2("quality.distribution")}>
        {bins.map((b, i) => (
          <rect key={i} x={i * 24 + 2} y={78 - (70 * b.count) / max} width={20} height={(70 * b.count) / max} fill="var(--color-primary)" opacity={0.75}>
            <title>{`${Math.round(b.from * 100)}–${Math.round(b.to * 100)}%: ${b.count}`}</title>
          </rect>
        ))}
      </svg>
      <figcaption className="xs muted">{t2("quality.distribution")}</figcaption>
    </figure>
  );
}

function ItemRow({ it, open, onToggle }: { it: ItemQuality; open: boolean; onToggle: () => void }) {
  const { t2, lang } = useMT();
  const warn = it.flags.some((f) => f.severity === "warn");
  return (
    <>
      <tr data-testid={`item-${it.code}`}>
        <td>
          <button type="button" className="btn btn-ghost btn-sm" aria-expanded={open} onClick={onToggle}>
            {open ? "▾" : "▸"} <span className="mono">{it.code}</span>
          </button>
        </td>
        <td className="num"><Share v={it.p_value} /></td>
        <td className="num"><Stat value={it.item_rest_correlation.value} reason={it.item_rest_correlation.unavailable_reason} /></td>
        <td className="num"><Stat value={it.upper_lower.value} reason={it.upper_lower.unavailable_reason} /></td>
        <td className="num"><Share v={it.omission_rate} /></td>
        <td>
          <div className="row" style={{ gap: 4 }}>
            {it.flags.length === 0 ? <span className="muted">—</span> : it.flags.map((f) => (
              <Badge key={f.code} tone={f.severity === "warn" ? "warn" : "info"} title={lang === "kz" ? f.message_kz : f.message_ru}>
                <CodeLabel prefix="flag." code={f.code} />
              </Badge>
            ))}
            {warn && <span className="sr-only">{t2("quality.flags")}</span>}
          </div>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6}>
            <div className="stack">
              <p style={{ margin: 0 }}>{lang === "kz" ? it.stem_kz : it.stem_ru}</p>
              <Messages items={it.flags} />
              <div className="table-wrap">
                <table className="table">
                  <caption className="sr-only">{t2("quality.distractors")}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{t2("quality.option")}</th><th scope="col" className="num">{t2("quality.chosen")}</th>
                      <th scope="col" className="num">{t2("quality.rest_mean")}</th><th scope="col" className="num">{t2("quality.pbis")}</th>
                      <th scope="col">{t2("quality.misconception")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {it.options.map((o) => (
                      <tr key={o.key}>
                        <td><span className="mono">{o.key}</span> {o.text} {o.is_key && <Badge tone="ok">{t2("quality.key")}</Badge>}</td>
                        <td className="num"><Num v={o.count} /> (<Share v={o.share_of_answered} />)</td>
                        <td className="num"><Share v={o.mean_rest_score} /></td>
                        <td className="num"><Stat value={o.point_biserial_rest.value} reason={o.point_biserial_rest.unavailable_reason} /></td>
                        <td className="mono xs">{o.misconception ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <KV rows={[
                [t2("quality.links"), <span key="l" className="small">{it.objectives.map((o) => `${o.code} (${o.status})`).join(", ") || "—"} · {it.misconceptions.join(", ") || "—"}</span>],
                [t2("quality.denominators"), <span key="d" className="small">{(["present", "answered", "omitted", "missing"] as const).map((k) => `${t2(`quality.den.${k}`)} ${it.denominators[k]}`).join(" · ")}</span>],
              ]} />
              <ItemAdmins id={it.item_id} />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function ItemAdmins({ id }: { id: string }) {
  const { t2 } = useMT();
  const [show, setShow] = useState(false);
  const q = useItemQuality(show ? id : null);
  if (!show) return <Button size="sm" onClick={() => setShow(true)}>{t2("quality.item_admins")}</Button>;
  return (
    <MQuery q={q}>
      {(d) => (
        <ul className="small" style={{ margin: 0 }}>
          {d.administrations.map((a) => (
            <li key={a.assessment.assessment_id}>
              <span className="mono">{a.assessment.code}</span> ({a.assessment.form_code}/{a.assessment.scale_code}): p = <Share v={a.stats.p_value} />,
              r = <Stat value={a.stats.item_rest_correlation.value} reason={a.stats.item_rest_correlation.unavailable_reason} />
            </li>
          ))}
          <li className="muted" title={d.pooled_unavailable_reason}>{t2("quality.not_pooled")}</li>
        </ul>
      )}
    </MQuery>
  );
}

export function QualityDetailPage() {
  const { assessmentId } = useParams();
  const { t2, lang } = useMT();
  const [rules, setRules] = useState<QualityRules>({ attempt_rule: "first", omitted_policy: "as_incorrect" });
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const q = useAssessmentQuality(assessmentId, rules);
  const nav = useNavigate();
  return (
    <div className="page stack">
      <MQuery q={q}>
        {(d) => {
          const f = d.form;
          const items = onlyFlagged ? d.items.filter((i) => i.flags.length > 0) : d.items;
          const misc = Array.from(new Set(d.items.filter((i) => i.flags.some((x) => x.severity === "warn")).flatMap((i) => i.misconceptions)));
          const topic = d.items.flatMap((i) => i.objectives).find((o) => o.topic_code)?.topic_code;
          return (
            <>
              <div className="page-header">
                <div>
                  <h1>{t2("quality.detail_title", { code: d.assessment.code })}</h1>
                  <p className="muted small">
                    {d.assessment.form_name} · <span className="mono">{d.assessment.form_code} / {d.assessment.scale_code}</span> ({d.assessment.linking_method}) ·{" "}
                    {t2("common.method")} <span className="mono">{d.method_version}</span> · {t2("common.data_version")} v{d.dataset_version} ·{" "}
                    {t2("common.generated")} {dateTime(d.generated_at, lang)} · analysis <code>{d.provenance.analysis_id.slice(0, 8)}</code>
                  </p>
                </div>
                <div className="row">
                  <Button onClick={() => nav("/quality")}>{t2("common.back")}</Button>
                  <Button variant="primary" onClick={() => nav(`/interventions?suggest=1${misc[0] ? `&misconception=${misc[0]}` : ""}${topic ? `&topic_code=${topic}` : ""}`)}>
                    {t2("quality.suggest")}
                  </Button>
                </div>
              </div>
              <StaleBanner ctx={{ is_stale: d.is_stale, dataset_version: d.dataset_version, current_dataset_version: d.current_dataset_version }} onRecompute={() => q.refetch()} />
              <RulesBar rules={rules} onChange={setRules} />
              <p className="xs muted">{t2("quality.rules", { attempt: t2(`quality.${d.rules.attempt_rule}`), omitted: t2(`quality.${d.rules.omitted_policy}`) })}</p>
              <div className="grid grid-3">
                <Card title={t2("quality.denominators")}>
                  <KV rows={[
                    [t2("quality.assigned"), <Num key="a" v={f.denominators.assigned} />],
                    [t2("quality.present"), <Num key="p" v={f.denominators.present} />],
                    [t2("quality.absent"), <Num key="b" v={f.denominators.absent} />],
                    [t2("quality.no_record"), <Num key="n" v={f.denominators.no_sitting_record} />],
                    [t2("quality.expected"), <Num key="e" v={f.denominators.expected_item_responses} />],
                    [t2("quality.completion"), <Share key="c" v={f.completion_rate} />],
                    [t2("quality.omission"), <Share key="o" v={f.omission_rate} />],
                    [t2("quality.missing"), <Share key="m" v={f.missing_rate} />],
                    [t2("quality.outside"), <Num key="out" v={f.denominators.present_outside_assignment} />],
                  ]} />
                  <p className="xs" style={{ marginTop: 8 }}><Badge tone={f.denominators.assigned_is_exact ? "ok" : "warn"}>
                    {t2(`quality.scope.${f.denominators.assignment_scope}`)}</Badge></p>
                </Card>
                <Card title={t2("quality.distribution")}>
                  <Histogram bins={f.score_distribution.histogram as unknown as { from: number; to: number; count: number }[]} />
                  <div className="row">
                    <Metric label={t2("quality.mean")} value={<Share v={f.score_distribution.mean} />} />
                    <Metric label={t2("quality.median")} value={<Share v={f.score_distribution.median} />} />
                    <Metric label={t2("quality.sd")} value={<Share v={f.score_distribution.sd} />} />
                  </div>
                  <p className="xs muted">{t2("quality.floor")}: <Share v={f.score_distribution.floor_share} /> · {t2("quality.ceiling")}: <Share v={f.score_distribution.ceiling_share} /></p>
                </Card>
                <Card title={t2("quality.reliability")}>
                  <Metric label={t2("quality.alpha")} value={<Stat value={f.reliability.cronbach_alpha.value} reason={f.reliability.cronbach_alpha.unavailable_reason} />}
                    sub={`${t2("quality.complete")}: ${f.reliability.n_complete_learners} · n ≥ ${f.reliability.min_learners}, k ≥ ${f.reliability.min_items}`} />
                  <h3 style={{ fontSize: "var(--text-sm)" }}>{t2("quality.slices")}</h3>
                  {Object.entries(d.slices).map(([dim, rows]) => (
                    <p key={dim} className="small" style={{ margin: 0 }}>
                      <span className="muted"><CodeLabel prefix="quality.dim." code={dim} />:</span>{" "}
                      {rows.map((s) => (s.suppressed ? `${s.value} — ${t2("quality.suppressed")}` : `${s.value}: n=${s.n}, ${Math.round((s.mean ?? 0) * 1000) / 10}%`)).join("; ") || "—"}
                    </p>
                  ))}
                </Card>
              </div>
              <Card title={t2("quality.items")} actions={
                <label className="row small" style={{ gap: 6 }}>
                  <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} /> {t2("quality.only_flagged")}
                </label>}>
                <div className="table-wrap">
                  <table className="table" data-testid="quality-items">
                    <caption className="sr-only">{t2("quality.items")}</caption>
                    <thead>
                      <tr>
                        <th scope="col">{t2("quality.item")}</th><th scope="col" className="num">{t2("quality.p")}</th>
                        <th scope="col" className="num">{t2("quality.r_it")}</th><th scope="col" className="num">{t2("quality.d")}</th>
                        <th scope="col" className="num">{t2("quality.omission")}</th><th scope="col">{t2("quality.flags")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it) => <ItemRow key={it.item_id} it={it} open={!!open[it.item_id]} onToggle={() => setOpen((o) => ({ ...o, [it.item_id]: !o[it.item_id] }))} />)}
                    </tbody>
                  </table>
                </div>
              </Card>
              <div className="grid grid-2">
                <Card title={t2("common.exclusions")}>
                  <KV rows={Object.entries(d.exclusions).map(([k, v]) => [<CodeLabel key={`l${k}`} prefix="excl." code={k} />, <Num key={k} v={v as number} />])} />
                </Card>
                <Card title={t2("common.limitations")}>
                  <Messages items={d.limitations} />
                </Card>
              </div>
              <AssignmentsCard assessmentId={d.assessment.assessment_id} />
              <DifCard assessmentId={d.assessment.assessment_id} />
            </>
          );
        }}
      </MQuery>
    </div>
  );
}

function AssignmentsCard({ assessmentId }: { assessmentId: string }) {
  const { t2 } = useMT();
  const q = useAssignments(assessmentId);
  const { canDraft } = useRoles();
  const [edit, setEdit] = useState<Record<string, boolean> | null>(null);
  const save = useMAction<{ cohort_ids: string[] }, unknown>("PUT", () => `/api/v1/quality/assessments/${assessmentId}/assignments`);
  return (
    <Card title={t2("quality.assignments")}>
      <MQuery q={q}>
        {(d) => (
          <div className="stack">
            <p className="small"><Badge tone={d.assignment_scope === "explicit" ? "ok" : "warn"}>{t2(`quality.scope.${d.assignment_scope}`)}</Badge></p>
            {edit ? (
              <form className="stack" aria-label={t2("quality.assignments_edit")}
                onSubmit={(e) => { e.preventDefault(); save.mutate({ cohort_ids: Object.keys(edit).filter((k) => edit[k]) }, { onSuccess: () => setEdit(null) }); }}>
                <p className="xs muted">{t2("quality.assignments_hint")}</p>
                <fieldset className="row" style={{ border: 0, padding: 0 }}>
                  <legend className="sr-only">{t2("quality.assignments")}</legend>
                  {d.cohorts.map((c) => (
                    <label key={c.cohort_id} className="row small" style={{ gap: 4 }}>
                      <input type="checkbox" checked={!!edit[c.cohort_id]} onChange={(e) => setEdit({ ...edit, [c.cohort_id]: e.target.checked })} />
                      <span className="mono">{c.code}</span> <span className="xs muted">({t2("quality.records", { n: c.sitting_records })})</span>
                    </label>
                  ))}
                </fieldset>
                <ActionError error={save.error} />
                <div className="row">
                  <Button type="submit" variant="primary" disabled={save.isPending}>{t2("common.save")}</Button>
                  <Button onClick={() => setEdit(null)}>{t2("common.cancel")}</Button>
                </div>
              </form>
            ) : (
              <>
                <p className="small" style={{ margin: 0 }}>
                  {d.cohorts.filter((c) => c.assigned).map((c) => `${c.code}${c.sitting_records === 0 ? " ⚠" : ""}`).join(", ") || "—"}
                </p>
                {canDraft && <Button size="sm" onClick={() => setEdit(Object.fromEntries(d.cohorts.map((c) => [c.cohort_id, c.assigned])))}>{t2("quality.assignments_edit")}</Button>}
              </>
            )}
          </div>
        )}
      </MQuery>
    </Card>
  );
}

function DifCard({ assessmentId }: { assessmentId: string }) {
  const { t2, lang } = useMT();
  const [open, setOpen] = useState(false);
  const q = useDif(open ? assessmentId : undefined);
  const fmt = (x: number | null | undefined) => (x === null || x === undefined ? "—" : x.toLocaleString(lang === "kz" ? "kk-KZ" : "ru-RU", { maximumFractionDigits: 2 }));
  return (
    <Card title={t2("dif.title")} id="dif">
      <p className="small muted">{t2("dif.lead")}</p>
      {!open ? <Button size="sm" onClick={() => setOpen(true)}>{t2("dif.run")}</Button> : (
        <MQuery q={q}>
          {(d) => (
            <div className="stack" data-testid="dif">
              <p className="small" style={{ margin: 0 }}>
                {t2("dif.groups", { ref: d.reference, focal: d.focal })}: {Object.entries(d.group_sizes).map(([g, n]) => `${g} — ${n ?? t2("fu.suppressed")}`).join(", ")}
              </p>
              {!d.available ? <Alert tone="info" role="note"><CodeLabel prefix="dif.unavailable." code={d.unavailable_reason} /></Alert> : (
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">{t2("dif.title")}</caption>
                    <thead><tr><th scope="col">{t2("quality.item")}</th><th scope="col" className="num">MH D-DIF</th><th scope="col">95%</th>
                      <th scope="col" className="num">p</th><th scope="col">{t2("dif.category")}</th></tr></thead>
                    <tbody>
                      {d.items.map((r) => (
                        <tr key={r.item_id}>
                          <th scope="row" className="mono">{r.code}</th>
                          <td className="num">{fmt(r.mh_d_dif)}</td>
                          <td className="small">{r.ci_low === null ? <CodeLabel prefix="dif.unavailable." code={r.unavailable_reason} /> : `${fmt(r.ci_low)} … ${fmt(r.ci_high)}`}</td>
                          <td className="num">{fmt(r.p_value)}</td>
                          <td>{r.category ? <Badge tone={r.category === "C" ? "warn" : r.category === "B" ? "info" : "ok"}>{t2(`dif.cat.${r.category}`)}</Badge> : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Messages items={d.limitations} />
              <p className="xs muted">{d.method_version}</p>
            </div>
          )}
        </MQuery>
      )}
    </Card>
  );
}
