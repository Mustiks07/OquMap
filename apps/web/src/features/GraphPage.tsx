import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useOverview } from "../api/hooks";
import { useGraph, type GraphNode } from "../api/wow";
import { useI18n } from "../i18n/I18n";
import type { DictKey, Lang } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Button, EmptyState, QueryView, Select, StaleBanner } from "../ui";
import { pct } from "../ui/format";
import { CouncilPanel } from "./Council";
import { EvidenceGraph, graphStatusText, NodeDetail } from "./EvidenceGraph";

function nodeMetric(node: GraphNode, lang: Lang): string {
  const m = node.metrics;
  if (typeof m.mean === "number") return pct(m.mean, lang);
  if (typeof m.p_correct === "number") return pct(m.p_correct, lang);
  if (typeof m.share_of_learners === "number") return `${pct(m.share_of_learners, lang)} · n=${m.n_learners ?? "—"}`;
  if (typeof m.planned_hours === "number") return `${m.planned_hours} ч`;
  return graphStatusText(node.code ?? node.status, lang);
}

function EvidenceRoute({ nodes, selected, onSelect }: { nodes: GraphNode[]; selected: string | null; onSelect: (id: string) => void }) {
  const { t, lang } = useI18n();
  return (
    <ol className="atlas-route" data-testid="graph-path" aria-label={t("graph.path")}>
      {nodes.map((node, index) => {
        const label = (lang === "kz" ? node.label_kz : node.label_ru) || node.id;
        const warning = node.kind === "gap" || ["not_measured", "unverified_mapping", "insufficient_data"].includes(node.status);
        return (
          <li key={node.id} className={selected === node.id ? "selected" : ""}>
            <button type="button" onClick={() => onSelect(node.id)} aria-pressed={selected === node.id}>
              <span className="atlas-route-index" aria-hidden="true">{index + 1}</span>
              <span className="atlas-route-kind">{t(`graph.kind.${node.kind}` as DictKey)}</span>
              <strong>{label}</strong>
              <span className="atlas-route-metric">{nodeMetric(node, lang) || node.status}</span>
              <span className={`atlas-route-proof ${warning ? "warning" : ""}`}>
                {warning ? (lang === "kz" ? "Тексеру қажет" : "Требует проверки") : (lang === "kz" ? "Негізі бар" : "Есть основание")}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** Evidence Atlas: a traceable route from measured signal to source, decision and verification. */
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
  useEffect(() => {
    const result = g.data?.result;
    if (!result) return;
    setSelected((current) => current && result.nodes.some((n) => n.id === current)
      ? current
      : result.path.map((id) => result.nodes.find((n) => n.id === id)).find((n) => n?.kind === "source")?.id ?? result.path[0] ?? null);
  }, [g.data?.context.analysis_id, g.data?.result]);

  if (!st.datasetId) return <div className="page"><EmptyState>{t("datasets.lead")}</EmptyState></div>;

  return (
    <div className="page atlas-page">
      <div className="atlas-toolbar">
        <div className="row" style={{ gap: 8 }}>
          <label className="small muted" htmlFor="graph-topic">{t("graph.topic")}</label>
          <Select id="graph-topic" value={topicId ?? ""} onChange={(v) => st.setTopicId(v)}
            options={topics.map((x) => ({ value: x.topic_id, label: `${x.code} ${pick(x as unknown as Record<string, unknown>, "title")} · ${x.score ? pct(x.score.mean, lang) : t(`status.${x.status}` as DictKey)}` }))} />
        </div>
        <div className="atlas-view-switch" role="group" aria-label={t("graph.title")}>
          <Button size="sm" aria-pressed={pathOnly} variant={pathOnly ? "primary" : "ghost"} onClick={() => setPathOnly(true)}>{t("graph.path_only")}</Button>
          <Button size="sm" aria-pressed={!pathOnly} variant={!pathOnly ? "primary" : "ghost"} onClick={() => setPathOnly(false)} data-testid="graph-full">{t("graph.full")}</Button>
        </div>
      </div>

      <QueryView q={g}>
        {(d) => {
          const route = d.result.path.map((id) => d.result.nodes.find((n) => n.id === id)).filter((n): n is GraphNode => !!n);
          const node = d.result.nodes.find((n) => n.id === selected) ?? null;
          const title = pick(d.result.topic as unknown as Record<string, unknown>, "title");
          const learners = route.map((n) => n.metrics.n_learners).find((v) => typeof v === "number");
          return (
            <>
              <StaleBanner ctx={d.context} />
              <section className="atlas-question-band" aria-labelledby="atlas-question">
                <div>
                  <span className="atlas-eyebrow">{lang === "kz" ? "Зерттеу сұрағы" : "Исследовательский вопрос"}</span>
                  <h1 id="atlas-question">{lang === "kz" ? `${title}: нәтиже неге төмен?` : `Почему проседает тема «${title}»?`}</h1>
                  <p>{lang === "kz"
                    ? "Әр түйін ашылады: сақталған есептеу, құрал беті, жауап жолдары, жоспар немесе шешім. Оқушы қатесі — диагноз емес, тексерілетін гипотеза."
                    : d.result.note_ru}</p>
                </div>
                <div className="atlas-audit" aria-label={lang === "kz" ? "Талдау паспорты" : "Паспорт анализа"}>
                  <span><strong>{route.length}</strong> {lang === "kz" ? "қадам" : "шагов"}</span>
                  <span><strong>{d.result.nodes.length}</strong> {lang === "kz" ? "дәлел" : "оснований"}</span>
                  <span><strong>v{d.context.dataset_version}</strong> data</span>
                </div>
              </section>

              <div className="atlas-workspace">
                <main className="atlas-canvas">
                  <div className="atlas-section-head">
                    <div>
                      <span className="atlas-eyebrow">Evidence Atlas</span>
                      <h2>{lang === "kz" ? "Дәлелдер маршруты" : "Атлас доказательств"}</h2>
                    </div>
                    <p>{lang === "kz" ? "Нәтижеден дереккөзге және тексерілетін шешімге дейін" : "От измеренного результата к источнику и проверяемому действию"}</p>
                  </div>

                  <div className="atlas-facts" aria-label={lang === "kz" ? "Зерттеу көлемі" : "Объём исследования"}>
                    <span><strong>{learners ?? "—"}</strong> {lang === "kz" ? "оқушы" : "учеников"}</span>
                    <span><strong>{d.result.gaps.length}</strong> {lang === "kz" ? "ашық сұрақ" : "открытых вопроса"}</span>
                    <span><strong>{d.context.method_version}</strong> {lang === "kz" ? "әдіс" : "метод"}</span>
                    <span className={d.result.gaps.length ? "warning" : ""}>{d.result.gaps.length ? (lang === "kz" ? "Себептілік дәлелденбеген" : "Причинность не доказана") : (lang === "kz" ? "Маршрут толық" : "Маршрут полный")}</span>
                  </div>

                  {pathOnly
                    ? <EvidenceRoute nodes={route} selected={selected} onSelect={setSelected} />
                    : <EvidenceGraph g={d.result} selected={selected} onSelect={setSelected} pathOnly={false} />}

                  <div className="atlas-decision-dock">
                    <div>
                      <span className="atlas-eyebrow">{lang === "kz" ? "Келесі тексерілетін қадам" : "Следующий проверяемый шаг"}</span>
                      <strong>{lang === "kz" ? "Пилотты жоспарлап, өлшеу хаттамасын сақтаңыз" : "Спланировать пилот и сохранить протокол измерения"}</strong>
                    </div>
                    <div className="row">
                      <Link className="btn" to="/sandbox">{t("sandbox.title")}</Link>
                      <Link className="btn btn-primary" to="/planner">{t("graph.open_plan")}</Link>
                    </div>
                  </div>
                </main>

                <aside className="atlas-inspector" aria-label={node ? t("graph.why") : t("graph.path")}>
                  <div className="atlas-inspector-head">
                    <div>
                      <span className="atlas-eyebrow">{lang === "kz" ? "Негіз инспекторы" : "Инспектор основания"}</span>
                      <h2>{node ? t(`graph.kind.${node.kind}` as DictKey) : t("graph.path")}</h2>
                    </div>
                    {node && <Button size="sm" variant="ghost" onClick={() => setSelected(null)} aria-label={lang === "kz" ? "Инспекторды жабу" : "Закрыть инспектор"}>×</Button>}
                  </div>
                  {node ? <NodeDetail node={node} /> : (
                    <div className="atlas-inspector-empty">
                      <p>{lang === "kz" ? "Дереккөзді, есептеуді және шектеуді көру үшін маршрут қадамын таңдаңыз." : "Выберите шаг маршрута, чтобы увидеть источник, вычисление и ограничение."}</p>
                    </div>
                  )}
                  <footer>
                    <span>analysis <code>{d.context.analysis_id.slice(0, 8)}</code></span>
                    <span>{d.context.is_stale ? (lang === "kz" ? "ескірген" : "устарел") : (lang === "kz" ? "өзекті" : "актуален")}</span>
                  </footer>
                </aside>
              </div>

              <section className="atlas-council">
                <div className="atlas-section-head">
                  <div><span className="atlas-eyebrow">AI Council</span><h2>{t("council.title")}</h2></div>
                  {!council && <p>{t("council.hint")}</p>}
                </div>
                {council ? <CouncilPanel topicId={d.result.topic.topic_id} autoRun /> : (
                  <Button variant="primary" onClick={() => setCouncil(true)} data-testid="run-council">{t("council.run")}</Button>
                )}
              </section>
            </>
          );
        }}
      </QueryView>
    </div>
  );
}
