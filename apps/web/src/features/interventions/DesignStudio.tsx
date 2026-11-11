/** Experiment Design Studio inside the pilot builder: deterministic design comparison (no LLM, no auto-approval). */
import { useState } from "react";
import { Alert, Badge, Button, Card, Field } from "../../ui";
import { useMAction } from "../measurement/api";
import type { components } from "../../api/schema";
import { ActionError, CodeLabel, Messages } from "../measurement/components";
import { useMT } from "../measurement/i18n";

type Req = components["schemas"]["DesignStudioRequest"];
type Out = components["schemas"]["DesignStudioOut"];

export function DesignStudio({ datasetId, cohortIds, assignmentUnit, onUseDesign }: {
  datasetId: string; cohortIds: string[]; assignmentUnit: "cohort" | "school"; onUseDesign: (design: string) => void;
}) {
  const { t2, lang } = useMT();
  const [p, setP] = useState({ icc_low: "0.05", icc_high: "0.2", baseline_r: "0.5", attrition: "0.1", effect_low: "0.15", effect_high: "0.35",
    mde_target: "", n_pre_measurements: "1", n_post_measurements: "1", calendar_weeks: "12", intervention_weeks: "6", comparison_available: true });
  const run = useMAction<Req, Out>("POST", () => "/api/v1/design-studio/evaluate");
  const num = (k: keyof typeof p, label: string, step = "0.01") => (
    <Field label={label}>{(id) => <input id={id} className="input input-num" type="number" step={step} value={String(p[k])}
      onChange={(e) => setP((x) => ({ ...x, [k]: e.target.value }))} />}</Field>
  );
  function evaluate() {
    run.mutate({
      dataset_id: datasetId, cohort_ids: cohortIds, assignment_unit: assignmentUnit, cluster_sizes: [], classes_share_schools: false,
      icc_low: Number(p.icc_low), icc_high: Number(p.icc_high), baseline_r: Number(p.baseline_r), attrition: Number(p.attrition),
      effect_low: Number(p.effect_low), effect_high: Number(p.effect_high), mde_target: p.mde_target ? Number(p.mde_target) : null,
      comparison_available: p.comparison_available, n_pre_measurements: Number(p.n_pre_measurements),
      n_post_measurements: Number(p.n_post_measurements), calendar_weeks: Number(p.calendar_weeks),
      intervention_weeks: Number(p.intervention_weeks), alpha: 0.05, target_power: 0.8,
    });
  }
  const r = run.data;
  const fmt = (x: number | null | undefined) => (x === null || x === undefined ? "—" : x.toLocaleString(lang === "kz" ? "kk-KZ" : "ru-RU", { maximumFractionDigits: 2 }));
  return (
    <Card title={t2("eds.title")} id="design-studio">
      <p className="small muted">{t2("eds.lead")}</p>
      <div className="grid grid-4">
        {num("icc_low", t2("eds.icc_low"))}{num("icc_high", t2("eds.icc_high"))}{num("baseline_r", t2("eds.baseline_r"))}{num("attrition", t2("eds.attrition"))}
        {num("effect_low", t2("eds.effect_low"))}{num("effect_high", t2("eds.effect_high"))}{num("mde_target", t2("eds.mde_target"))}
        {num("calendar_weeks", t2("eds.calendar_weeks"), "1")}{num("intervention_weeks", t2("eds.intervention_weeks"), "1")}
        {num("n_pre_measurements", t2("eds.n_pre"), "1")}{num("n_post_measurements", t2("eds.n_post"), "1")}
      </div>
      <label className="row small" style={{ gap: 6 }}>
        <input type="checkbox" checked={p.comparison_available} onChange={(e) => setP((x) => ({ ...x, comparison_available: e.target.checked }))} /> {t2("eds.comparison_available")}
      </label>
      <div className="row" style={{ marginTop: 8 }}>
        <Button onClick={evaluate} disabled={run.isPending || cohortIds.length === 0}>{t2("eds.run")}</Button>
        {cohortIds.length === 0 && <span className="xs muted">{t2("eds.need_cohorts")}</span>}
      </div>
      <ActionError error={run.error} />
      {r && (
        <div className="stack" style={{ marginTop: 12 }} data-testid="design-studio-result">
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">{t2("eds.title")}</caption>
              <thead><tr>
                <th scope="col">{t2("pilot.design")}</th><th scope="col">{t2("eds.admissible")}</th><th scope="col">{t2("pilot.ceiling")}</th>
                <th scope="col" className="num">{t2("eds.clusters")}</th><th scope="col" className="num">MDE (SD)</th>
                <th scope="col" className="num">{t2("eds.power")}</th><th scope="col">{t2("eds.risks")}</th><th scope="col" />
              </tr></thead>
              <tbody>
                {r.designs.map((d) => (
                  <tr key={d.design}>
                    <th scope="row">{t2(`pilot.design.${d.design}`)}</th>
                    <td>{d.admissible ? <Badge tone="ok">{t2("common.yes")}</Badge> : <Badge tone="warn">{t2("common.none")}</Badge>}</td>
                    <td className="small"><CodeLabel prefix="causal." code={d.causal_ceiling} /></td>
                    <td className="num">{String(d.clusters.intervention)} / {String(d.clusters.comparison)}</td>
                    <td className="num">{d.mde_range ? `${fmt(d.mde_range.low as number)}–${fmt(d.mde_range.high as number)}` : <span className="xs muted"><CodeLabel prefix="eds.unavailable." code={d.precision_unavailable_reason} /></span>}</td>
                    <td className="num">{d.power_range ? `${fmt(d.power_range.low as number)}–${fmt(d.power_range.high as number)}` : "—"}</td>
                    <td className="xs">{Object.entries(d.risks).map(([k, v]) => `${t2(`eds.risk.${k}`)}: ${t2(`eds.level.${v}`)}`).join("; ")}</td>
                    <td>{d.admissible && <Button size="sm" onClick={() => onUseDesign(d.design)}>{t2("eds.use")}</Button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {r.designs.filter((d) => d.sensitivity.length > 0).map((d) => (
            <details key={d.design}>
              <summary className="small">{t2("eds.sensitivity")}: {t2(`pilot.design.${d.design}`)}</summary>
              <table className="table">
                <caption className="sr-only">{t2("eds.sensitivity")}</caption>
                <thead><tr><th scope="col">ICC</th><th scope="col">{t2("eds.effect")}</th><th scope="col" className="num">{t2("eds.power")}</th></tr></thead>
                <tbody>{d.sensitivity.map((s, i) => <tr key={i}><td>{fmt(s.icc as number)}</td><td>{fmt(s.effect as number)}</td><td className="num">{fmt(s.power as number)}</td></tr>)}</tbody>
              </table>
              <Messages items={d.messages} />
            </details>
          ))}
          <Alert tone="info" role="note">{t2("eds.no_auto")}</Alert>
          <Messages items={r.warning_messages} />
          <p className="xs muted">{r.method_version} · {r.formula}</p>
        </div>
      )}
    </Card>
  );
}
