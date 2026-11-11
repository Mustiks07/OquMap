import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useOverview } from "../api/hooks";
import { useGraph } from "../api/wow";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Badge, Button, Card, EmptyState, QueryView, Select, StaleBanner } from "../ui";
import { pct } from "../ui/format";
import { CouncilPanel } from "./Council";
import { EvidenceGraph, NodeDetail } from "./EvidenceGraph";

/** Hero screen: click a weak topic → a verifiable chain down to the decision and its follow-up. */
export function GraphPage() {
  const { t, lang, pick } = useI18n();
  const params = useParams();
  const st = useAppState();
  const ov = useOverview();
  const topics = useMemo(() => {
    const rows = ov.data?.result.topics ?? [];
    return [...rows].sort((a, b) => (a.score?.mean ?? 2) - (b.score?.mean ?? 2));
  }, [ov.data]);
  const topicId = params.topicId ?? st.topicId ?? topics.find((x) => x.status === "difficult")?.topic_id ?? topics[0]?.topic_id ?? null;
  useEffect(() => {
    if (topicId && topicId !== st.topicId) st.setTopicId(topicId);
  }, [topicId, st]);
  const g = useGraph(topicId);
  const [selected, setSelected] = useState<string | null>(null);
  const [pathOnly, setPathOnly] = useState(true);
  const [council, setCouncil] = useState(false);
  useEffect(() => setSelected(null), [topicId]);
  if (!st.datasetId) return <div className="page"><EmptyState>{t("datasets.lead")}</EmptyState></div>;
  const node = g.data?.result.nodes.find((n) => n.id === selected) ?? null;
  return (
    <div className="page stack">
      <div className="page-header">
        <h1>{t("graph.title")}</h1>
        <p className="muted">{t("graph.lead")}</p>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <label className="small" htmlFor="graph-topic">{t("graph.topic")}</label>
        <Select id="graph-topic" value={topicId ?? ""} onChange={(v) => st.setTopicId(v)}
          options={topics.map((x) => ({ value: x.topic_id, label: `${x.code} ${pick(x as unknown as Record<string, unknown>, "title")} · ${x.score ? pct(x.score.mean, lang) : t(`status.${x.status}` as DictKey)}` }))} />
        <Button size="sm" aria-pressed={pathOnly} variant={pathOnly ? "primary" : "default"} onClick={() => setPathOnly(true)}>{t("graph.path_only")}</Button>
        <Button size="sm" aria-pressed={!pathOnly} variant={!pathOnly ? "primary" : "default"} onClick={() => setPathOnly(false)} data-testid="graph-full">{t("graph.full")}</Button>
      </div>
      <QueryView q={g}>
        {(d) => (
          <>
            <StaleBanner ctx={d.context} />
            <div className="graph-layout">
              <Card title={`${d.result.topic.code} ${pick(d.result.topic as unknown as Record<string, unknown>, "title")}`}>
                <EvidenceGraph g={d.result} selected={selected} onSelect={setSelected} pathOnly={pathOnly} />
                <p className="xs muted">{d.result.note_ru}</p>
              </Card>
              <Card title={node ? t("graph.why") : t("graph.path")}>
                {node ? (
                  <>
                    <NodeDetail node={node} />
                    <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>← {t("graph.path")}</Button>
                  </>
                ) : (
                  <ol className="stack path-list" data-testid="graph-path">
                    {d.result.path.map((id, i) => {
                      const n = d.result.nodes.find((x) => x.id === id)!;
                      return (
                        <li key={id}>
                          <button type="button" className="linklike" onClick={() => setSelected(id)}>
                            <Badge tone={n.kind === "gap" ? "warn" : "info"}>{`${i + 1} · ${t(`graph.kind.${n.kind}` as DictKey)}`}</Badge>{" "}
                            {lang === "kz" ? n.label_kz : n.label_ru}
                          </button>
                        </li>
                      );
                    })}
                  </ol>
                )}
                {d.result.gaps.length > 0 && !node && (
                  <p className="xs muted">{t("graph.gaps", { n: d.result.gaps.length })}</p>
                )}
              </Card>
            </div>
            <Card title={t("council.title")}>
              {council ? <CouncilPanel topicId={d.result.topic.topic_id} autoRun /> : (
                <div className="row">
                  <Button variant="primary" onClick={() => setCouncil(true)} data-testid="run-council">{t("council.run")}</Button>
                  <span className="xs muted">{t("council.hint")}</span>
                </div>
              )}
            </Card>
          </>
        )}
      </QueryView>
    </div>
  );
}
