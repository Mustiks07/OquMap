import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useConfig, useDatasets, useQuality } from "../api/hooks";
import type { DatasetSummary, QualityReport } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, Disclosure, EmptyState, ErrorState, QueryView, SyntheticBadge } from "../ui";
import { dateTime, num } from "../ui/format";

export function DatasetsPage() {
  const { t, lang } = useI18n();
  const q = useDatasets();
  const cfg = useConfig();
  const { user, datasetId, setDatasetId } = useAppState();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const recommendedCode = cfg.data?.recommended_dataset_code ?? "base";

  async function loadLab(code: string) {
    setLoading(code);
    setError(null);
    try {
      const d = await api.post<DatasetSummary>(`/api/v1/demo/scenarios/${code}`);
      await qc.invalidateQueries({ queryKey: ["datasets"] });
      setDatasetId(d.id);
      nav("/compare");
    } catch (e) {
      setError(e);
    } finally {
      setLoading(null);
    }
  }

  const card = (d: DatasetSummary, primary: boolean) => (
    <Card key={d.id} title={lang === "kz" ? d.name_kz : d.name_ru}
      actions={d.id === datasetId ? <Badge tone="ok">{t("datasets.selected")}</Badge> : null}>
      <p className="small">{lang === "kz" ? d.description_kz : d.description_ru}</p>
      <div className="row" style={{ marginBottom: 12 }}>
        {d.is_synthetic && <SyntheticBadge />}
        <Badge tone="info">{t(`level.${d.data_level}` as DictKey)}</Badge>
        <Badge>v{d.version}</Badge>
      </div>
      <Button variant={primary ? "primary" : "default"} data-testid={`choose-${d.code}`}
        onClick={() => { setDatasetId(d.id); nav(d.data_level === "setup" ? "/import" : "/overview"); }}>
        {d.data_level === "setup" ? t("datasets.own_data") : t("datasets.open_overview")}
      </Button>
    </Card>
  );

  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t("datasets.title")}</h1>
          <p className="muted">{t("datasets.lead")}</p>
        </div>
        <Button onClick={() => nav("/import")} data-testid="own-data">{t("datasets.own_data")}</Button>
      </div>
      {error ? <ErrorState error={error} /> : null}
      <QueryView q={q}>
        {(ds) => {
          const rec = ds.find((d) => d.code === recommendedCode && d.is_synthetic);
          const lab = ds.filter((d) => d !== rec && d.is_synthetic && !!d.scenario);
          const projects = ds.filter((d) => d !== rec && !lab.includes(d));
          const labCodes = new Set(lab.map((d) => d.code));
          const missingLab = (cfg.data?.lab_scenarios ?? []).filter((c) => !labCodes.has(c));
          return (
            <>
              {rec && (
                <section aria-labelledby="rec-title" className="stack">
                  <h2 id="rec-title">{t("datasets.recommended")}</h2>
                  {card(rec, true)}
                </section>
              )}
              {projects.length > 0 && (
                <section className="stack">
                  <h2>{t("datasets.projects")}</h2>
                  <div className="grid grid-2">{projects.map((d) => card(d, !rec))}</div>
                </section>
              )}
              {ds.length === 0 && <EmptyState><Button variant="primary" onClick={() => nav("/import")}>{t("datasets.own_data")}</Button></EmptyState>}
              {user?.org_is_demo && (lab.length > 0 || missingLab.length > 0) && (
                <section className="stack">
                  <Disclosure summary={t("datasets.lab")}>
                    <p className="small muted">{t("datasets.lab_note")}</p>
                    <div className="grid grid-2">
                      {lab.map((d) => card(d, false))}
                      {missingLab.map((c) => (
                        <Card key={c} title={t(`lab.${c}` as DictKey)}>
                          <Button onClick={() => loadLab(c)} disabled={loading !== null} data-testid={`load-${c}`}>
                            {loading === c ? t("common.loading") : t("datasets.load")}
                          </Button>
                        </Card>
                      ))}
                    </div>
                  </Disclosure>
                </section>
              )}
            </>
          );
        }}
      </QueryView>
    </div>
  );
}

export function QualityPage() {
  const { t } = useI18n();
  const { datasetId } = useAppState();
  return (
    <div className="page stack">
      <div className="page-header"><h1>{t("quality.title")}</h1></div>
      {datasetId ? <QualityPanel /> : <EmptyState>{t("datasets.lead")}</EmptyState>}
    </div>
  );
}

export function QualityPanel() {
  const { t, lang } = useI18n();
  const q = useQuality();
  return (
    <QueryView q={q}>
      {(r: QualityReport) => (
        <Card title={t("quality.title")} id="quality">
          <div className="grid grid-4" style={{ marginBottom: 16 }}>
            <div className="metric"><span className="metric-label">{t("common.learners")}</span><span className="metric-value">{num(r.counts.learners, lang)}</span></div>
            <div className="metric"><span className="metric-label">{t("common.classes")}</span><span className="metric-value">{num(r.counts.classes, lang)}</span></div>
            <div className="metric"><span className="metric-label">{t("common.schools")}</span><span className="metric-value">{num(r.counts.schools, lang)}</span></div>
            <div className="metric"><span className="metric-label">{t("datasets.level")}</span><span className="small">{t(`level.${r.data_level}` as DictKey)}</span></div>
          </div>
          <h3>{t("quality.assessments")}</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Код</th><th>Этап</th><th>Форма</th><th>{t("quality.scale")}</th><th>{t("quality.linking")}</th>
                  <th className="num">{t("quality.responses")}</th><th className="num">{t("quality.omitted")}</th>
                  <th className="num">{t("quality.absent")}</th><th className="num">{t("quality.retakes")}</th>
                </tr>
              </thead>
              <tbody>
                {r.assessments.map((a) => (
                  <tr key={a.assessment_id}>
                    <td className="mono">{a.code}</td><td>{a.stage}</td><td className="mono">{a.form}</td><td className="mono">{a.scale}</td>
                    <td>{a.linking_method}</td><td className="num">{num(a.n_responses, lang)}</td><td className="num">{num(a.omitted, lang)}</td>
                    <td className="num">{num(a.absent, lang)}</td><td className="num">{num(a.retake_rows, lang)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="xs muted" style={{ marginTop: 8 }}>{t("quality.rules")}</p>
          <div className="grid grid-2" style={{ marginTop: 12 }}>
            <div>
              <h3>{t("quality.possible")}</h3>
              <div className="chip-row">{r.capabilities.possible.map((c) => <Badge key={c} tone="ok">{c}</Badge>)}</div>
            </div>
            <div>
              <h3>{t("quality.missing")}</h3>
              <div className="chip-row">{r.capabilities.missing.map((c) => <Badge key={c} tone="warn">{c}</Badge>)}</div>
            </div>
          </div>
          {r.data_level === "grades_only" && <div style={{ marginTop: 12 }}><Alert tone="warn">{t("level.grades_only")}: {r.capabilities.missing.join(", ")}</Alert></div>}
          <h3 style={{ marginTop: 16 }}>{t("quality.versions")}</h3>
          <ul className="small">
            {r.versions.map((v) => (
              <li key={v.version}>v{v.version} — {v.reason} · {dateTime(v.at, lang)}</li>
            ))}
          </ul>
        </Card>
      )}
    </QueryView>
  );
}
