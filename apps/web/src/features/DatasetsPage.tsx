import { useNavigate } from "react-router-dom";
import { useDatasets, useQuality } from "../api/hooks";
import type { QualityReport } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, EmptyState, QueryView, SyntheticBadge } from "../ui";
import { dateTime, num } from "../ui/format";

export function DatasetsPage() {
  const { t, lang } = useI18n();
  const q = useDatasets();
  const { datasetId, setDatasetId } = useAppState();
  const nav = useNavigate();
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>{t("datasets.title")}</h1>
          <p className="muted">{t("datasets.lead")}</p>
        </div>
      </div>
      <QueryView q={q} empty={(d) => d.length === 0}>
        {(ds) => (
          <div className="grid grid-2">
            {ds.map((d) => (
              <Card key={d.id} title={lang === "kz" ? d.name_kz : d.name_ru}
                actions={d.id === datasetId ? <Badge tone="ok">{t("datasets.selected")}</Badge> : null}>
                <p className="small">{lang === "kz" ? d.description_kz : d.description_ru}</p>
                <div className="row" style={{ marginBottom: 12 }}>
                  {d.is_synthetic && <SyntheticBadge />}
                  <Badge tone="info">{t(`level.${d.data_level}` as DictKey)}</Badge>
                  <Badge>v{d.version}</Badge>
                  {d.scenario && <Badge>{t("datasets.scenario")}: {d.scenario}</Badge>}
                </div>
                <Button variant={d.id === datasetId ? "default" : "primary"} data-testid={`choose-${d.code}`}
                  onClick={() => { setDatasetId(d.id); nav("/import"); }}>
                  {t("datasets.choose")}
                </Button>
              </Card>
            ))}
          </div>
        )}
      </QueryView>
      {q.data && q.data.length === 0 && <EmptyState />}
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
