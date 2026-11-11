import { useNavigate } from "react-router-dom";
import { useCurrentDataset, useOverview } from "../api/hooks";
import type { OverviewResult, TopicOverviewRow } from "../api/types";
import { useI18n } from "../i18n/I18n";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, CI, Card, EmptyState, QueryView, ShareBar, StaleBanner, StatusBadge } from "../ui";
import { heatColor } from "../ui/charts";
import { num, pct } from "../ui/format";
import { FilterBar } from "./Filters";

export function NeedDataset() {
  const { t } = useI18n();
  const nav = useNavigate();
  return (
    <EmptyState>
      <p>{t("datasets.lead")}</p>
      <Button variant="primary" onClick={() => nav("/datasets")}>{t("nav.datasets")}</Button>
    </EmptyState>
  );
}

export function OverviewPage() {
  const { t, lang, pick } = useI18n();
  const { datasetId, setTopicId } = useAppState();
  const { dataset } = useCurrentDataset();
  const q = useOverview();
  const nav = useNavigate();
  if (!datasetId) return <NeedDataset />;
  const open = (id: string) => {
    setTopicId(id);
    nav(`/topic/${id}`);
  };
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t("overview.title")}</h1>
          <p className="muted">{t("overview.lead")}</p>
        </div>
      </div>
      <FilterBar />
      <QueryView q={q}>
        {(env) => {
          const r: OverviewResult = env.result;
          const byId = new Map(r.topics.map((tp) => [tp.topic_id, tp]));
          return (
            <>
              <StaleBanner ctx={env.context} onRecompute={() => q.refetch()} />
              <p className="small muted" data-testid="overview-counts">
                {t("overview.counts", { learners: num(r.counts.n_learners, lang), classes: num(r.counts.n_classes, lang), schools: num(r.counts.n_schools, lang), responses: num(r.counts.n_responses, lang) })}
                {" · "}
                {t("overview.excluded", { absent: num(r.counts.absent_sittings, lang), omitted: num(r.counts.omitted_responses, lang) })}
                {" · "}analysis <code>{env.context.analysis_id.slice(0, 8)}</code>, data v{env.context.dataset_version}
              </p>
              <div className="grid grid-2">
                <Card title={t("overview.priorities")}>
                  {r.priorities.length === 0 ? <EmptyState /> : (
                    <ol className="stack" style={{ paddingLeft: 18, margin: 0 }}>
                      {r.priorities.map((p) => {
                        const tp = byId.get(p.topic_id as string)!;
                        return (
                          <li key={tp.topic_id}>
                            <div className="spread">
                              <span><strong>{tp.code}</strong> {pick(tp, "title")}</span>
                              <Button size="sm" variant="primary" onClick={() => open(tp.topic_id)} data-testid={`open-topic-${tp.code}`}>{t("overview.open_topic")}</Button>
                            </div>
                            <ShareBar value={tp.score?.mean} label={tp.code} />
                            <CI low={tp.score?.ci_low} high={tp.score?.ci_high} reason={tp.score?.ci_unavailable_reason} />
                          </li>
                        );
                      })}
                    </ol>
                  )}
                </Card>
                <Card title={t("overview.coverage_gaps")}>
                  {r.coverage_gaps.length === 0 ? <EmptyState /> : (
                    <ul className="stack" style={{ paddingLeft: 18, margin: 0 }}>
                      {r.coverage_gaps.map((g) => {
                        const tp = byId.get(g.topic_id as string)!;
                        return (
                          <li key={tp.topic_id}>
                            <strong>{tp.code}</strong> {pick(tp, "title")} <StatusBadge status={tp.status} />
                            <div className="xs muted">{tp.n_items_proposed_only > 0 ? `${tp.n_items_proposed_only} ${t("topic.n_items_prop")}` : tp.status_reason}</div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  <p className="xs muted" style={{ marginTop: 8 }}>{t("bands.note")}</p>
                </Card>
              </div>
              <Card title={t("overview.topics")}>
                <div className="table-wrap">
                  <table className="table" data-testid="topics-table">
                    <thead>
                      <tr>
                        <th>{t("compare.topic")}</th><th>{t("common.status")}</th><th style={{ minWidth: 180 }}>{t("overview.score")}</th>
                        <th>{t("common.ci95")}</th><th className="num">n</th><th className="num">{t("overview.items")}</th><th>{t("overview.coverage")}</th><th />
                      </tr>
                    </thead>
                    <tbody>
                      {r.topics.map((tp: TopicOverviewRow) => (
                        <tr key={tp.topic_id} className="clickable" onClick={() => open(tp.topic_id)}>
                          <td><strong>{tp.code}</strong> {pick(tp, "title")}</td>
                          <td><StatusBadge status={tp.status} /></td>
                          <td>{tp.score ? <ShareBar value={tp.score.mean} label={tp.code} /> : <span className="muted">—</span>}</td>
                          <td className="xs">{tp.score?.ci_low != null ? `${pct(tp.score.ci_low, lang)} – ${pct(tp.score.ci_high, lang)}` : "—"}</td>
                          <td className="num">{tp.score ? `${num(tp.score.n_learners, lang)} / ${tp.score.n_classes}` : "—"}</td>
                          <td className="num">{tp.n_items}</td>
                          <td className="small">{tp.objectives_measured}/{tp.objectives_total}</td>
                          <td><Button size="sm" onClick={(e) => { e.stopPropagation(); open(tp.topic_id); }}>{t("common.open")}</Button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="xs muted" style={{ marginTop: 8 }}>{t("common.share_note")} n = {t("common.learners")} / {t("common.classes")}.</p>
              </Card>
              <Card title={t("overview.heatmap")}>
                {r.heatmap.cells.length === 0 ? <EmptyState /> : (
                  <>
                    <div className="table-wrap">
                      <table className="table" aria-label={t("overview.heatmap")}>
                        <thead>
                          <tr>
                            <th>{t("compare.topic")}</th>
                            {r.heatmap.cohorts.map((c) => (
                              <th key={c.cohort_id} className="xs" title={`${c.school_code} · ${c.edition_code ?? ""}`} style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", padding: "6px 2px" }}>
                                {c.code} {c.edition_code ? `· ${c.edition_code}` : ""}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {r.topics.filter((tp) => tp.score).map((tp) => (
                            <tr key={tp.topic_id}>
                              <td className="small"><strong>{tp.code}</strong></td>
                              {r.heatmap.cohorts.map((c) => {
                                const cell = r.heatmap.cells.find((x) => x.topic_id === tp.topic_id && x.cohort_id === c.cohort_id);
                                return (
                                  <td key={c.cohort_id} className="heat-cell" style={{ background: heatColor(cell?.mean) }} title={cell ? `${c.code}: ${pct(cell.mean, lang)} (n=${cell.n})` : "—"}>
                                    {cell ? Math.round(cell.mean * 100) : ""}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="xs muted" style={{ marginTop: 8 }}>Значения — доля баллов класса, %; пустая клетка — нет измерения.</p>
                  </>
                )}
              </Card>
              {dataset?.is_synthetic && <Alert tone="info">{t("synthetic.note")}</Alert>}
              <div className="row"><Badge>method {env.context.method_version}</Badge></div>
            </>
          );
        }}
      </QueryView>
    </div>
  );
}
