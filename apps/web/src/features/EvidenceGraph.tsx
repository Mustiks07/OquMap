import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAnalysis, type GraphNode, type GraphResult } from "../api/wow";
import { useI18n } from "../i18n/I18n";
import type { DictKey, Lang } from "../i18n/dict";
import { Badge, Button, Loading, type Tone } from "../ui";
import { pct } from "../ui/format";
import { SourceDialog } from "./SourceDialog";

const LANES: GraphNode["kind"][] = ["prerequisite", "topic", "objective", "item", "misconception", "source", "hours", "decision", "followup"];
const W = 176;
const H = 34;
const GAP_Y = 10;
const LANE_W = 214;
const PATH_COLS = 3;
const PATH_STEP = 236;

const GRAPH_STATUS: Record<string, [string, string]> = {
  proposed: ["предложено", "ұсынылған"],
  approved: ["утверждено", "бекітілген"],
  draft: ["черновик", "жоба"],
  active: ["активно", "белсенді"],
  measured: ["измерено", "өлшенген"],
  not_measured: ["не измерено", "өлшенбеген"],
  unverified_mapping: ["разметка не подтверждена", "белгілеу расталмаған"],
  insufficient_data: ["мало данных", "деректер аз"],
  no_decision: ["решения пока нет", "шешім әзірге жоқ"],
  no_follow_up: ["нет повторного измерения", "қайта өлшеу жоқ"],
  no_plan_hours: ["часы не назначены", "сағаттар бөлінбеген"],
};

export function graphStatusText(status: string, lang: Lang): string {
  const label = GRAPH_STATUS[status];
  return label ? label[lang === "kz" ? 1 : 0] : status.replaceAll("_", " ");
}

function tone(n: GraphNode): Tone {
  if (n.kind === "gap") return "warn";
  if (n.kind === "misconception") return "synthetic";
  if (["not_measured", "unverified_mapping", "insufficient_data"].includes(n.status)) return "neutral";
  const v = (n.metrics.mean ?? n.metrics.p_correct) as number | null | undefined;
  if (typeof v === "number") return v < 0.5 ? "danger" : v < 0.65 ? "warn" : "ok";
  return "info";
}

function metricText(n: GraphNode, lang: Lang): string {
  const m = n.metrics;
  if (typeof m.mean === "number") return pct(m.mean, lang);
  if (typeof m.p_correct === "number") return pct(m.p_correct, lang);
  if (typeof m.share_of_learners === "number") return `${pct(m.share_of_learners, lang)} · ${m.n_learners}`;
  if (typeof m.planned_hours === "number") return `${m.planned_hours} ч`;
  return "";
}

/** Layered evidence graph; the verifiable path is highlighted and every node opens what it is based on. */
export function EvidenceGraph({ g, selected, onSelect, pathOnly }: { g: GraphResult; selected: string | null; onSelect: (id: string) => void; pathOnly: boolean }) {
  const { lang, t } = useI18n();
  const pathSet = useMemo(() => new Set(g.path), [g.path]);
  const layout = useMemo(() => {
    const parentLane: Record<string, number> = {};
    for (const e of g.edges) if (e.kind === "gap") parentLane[e.to] = LANES.indexOf(g.nodes.find((n) => n.id === e.from)?.kind ?? "topic");
    if (pathOnly) {  // compact flow: the chain in order, three per row
      const pos: Record<string, { x: number; y: number; lane: number }> = {};
      g.path.forEach((id, i) => (pos[id] = { x: 12 + (i % PATH_COLS) * PATH_STEP, y: 30 + Math.floor(i / PATH_COLS) * 78, lane: i }));
      return { pos, height: 40 + Math.ceil(g.path.length / PATH_COLS) * 78, usedLanes: [] as number[], width: 24 + PATH_COLS * PATH_STEP };
    }
    const lanes: Record<number, GraphNode[]> = {};
    for (const n of g.nodes) {
      if (pathOnly && !pathSet.has(n.id)) continue;
      const lane = n.kind === "gap" ? Math.min((parentLane[n.id] ?? 1) + 1, LANES.length - 1) : LANES.indexOf(n.kind);
      (lanes[lane] ??= []).push(n);
    }
    const pos: Record<string, { x: number; y: number; lane: number }> = {};
    let maxRows = 0;
    Object.entries(lanes).forEach(([lane, ns]) => {
      ns.sort((a, b) => Number(pathSet.has(b.id)) - Number(pathSet.has(a.id)));
      ns.forEach((n, i) => (pos[n.id] = { x: 12 + Number(lane) * LANE_W, y: 30 + i * (H + GAP_Y), lane: Number(lane) }));
      maxRows = Math.max(maxRows, ns.length);
    });
    return { pos, height: 40 + maxRows * (H + GAP_Y), usedLanes: Object.keys(lanes).map(Number), width: 24 + LANES.length * LANE_W };
  }, [g, pathOnly, pathSet]);
  const pathEdges = useMemo(() => {
    const s = new Set<string>();
    for (let i = 0; i + 1 < g.path.length; i++) s.add(`${g.path[i]}>${g.path[i + 1]}`).add(`${g.path[i + 1]}>${g.path[i]}`);
    return s;
  }, [g.path]);
  return (
    <div className="graph-scroll" data-testid="evidence-graph">
      <svg width={layout.width} height={layout.height} role="group" aria-label={t("graph.title")}>
        {LANES.map((k, i) => layout.usedLanes.includes(i) && (
          <text key={k} x={12 + i * LANE_W} y={16} className="graph-lane">{t(`graph.kind.${k}` as DictKey)}</text>
        ))}
        {g.edges.map((e, i) => {
          const a = layout.pos[e.from];
          const b = layout.pos[e.to];
          if (!a || !b) return null;
          const onPath = pathEdges.has(`${e.from}>${e.to}`);
          if (pathOnly && !onPath) return null;
          if (pathOnly && a.y !== b.y) {  // wrap to the next row
            const [u, v] = a.y < b.y ? [a, b] : [b, a];
            return <path key={i} d={`M${u.x + W / 2} ${u.y + H} C ${u.x + W / 2} ${u.y + H + 30}, ${v.x + W / 2} ${v.y - 30}, ${v.x + W / 2} ${v.y}`}
              className={`graph-edge${onPath ? " on-path" : ""}`} />;
          }
          const [l, r] = a.x <= b.x ? [a, b] : [b, a];
          const x1 = l.x + W, y1 = l.y + H / 2, x2 = r.x, y2 = r.y + H / 2;
          const d = l.lane === r.lane ? `M${l.x + W} ${y1} C ${l.x + W + 30} ${y1}, ${r.x + W + 30} ${y2}, ${r.x + W} ${y2}`
            : `M${x1} ${y1} C ${x1 + 40} ${y1}, ${x2 - 40} ${y2}, ${x2} ${y2}`;
          return <path key={i} d={d} className={`graph-edge${onPath ? " on-path" : ""}${e.kind === "gap" ? " gap" : ""}`} />;
        })}
        {g.nodes.map((n) => {
          const p = layout.pos[n.id];
          if (!p) return null;
          const label = (lang === "kz" ? n.label_kz : n.label_ru) || n.id;
          const m = metricText(n, lang);
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} className={`graph-node tone-${tone(n)}${pathSet.has(n.id) ? " on-path" : ""}${selected === n.id ? " selected" : ""}`}
              role="button" tabIndex={0} data-node={n.id} data-kind={n.kind}
              onClick={() => onSelect(n.id)} onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect(n.id); } }}>
              <title>{`${t(`graph.kind.${n.kind}` as DictKey)}: ${label}${m ? `, ${m}` : ""}`}</title>
              {pathOnly && <text x={0} y={-5} className="graph-lane">{t(`graph.kind.${n.kind}` as DictKey)}</text>}
              <rect width={W} height={H} rx={6} />
              <text x={8} y={14} className="graph-label">{label.length > 26 ? label.slice(0, 25) + "…" : label}</text>
              <text x={8} y={28} className="graph-metric">{m || t(`graph.kind.${n.kind}` as DictKey)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function at(obj: unknown, path: string): unknown {
  let cur: unknown = obj;
  for (const part of path.replace(/\[(\d+)\]/g, ".$1").split(".")) {
    if (cur == null) return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

/** What a node is based on: the stored calculation, the answer rows, the page, the plan row or the decision. */
export function NodeDetail({ node }: { node: GraphNode }) {
  const { t, lang } = useI18n();
  const [source, setSource] = useState<string | null>(null);
  const a = useAnalysis(node.open?.type === "calculation" || node.open?.type === "item" ? node.open.analysis_id : null);
  const label = lang === "kz" ? node.label_kz : node.label_ru;
  const piece = a.data && node.open?.path ? at(a.data.result, node.open.path) : undefined;
  return (
    <div className="stack" data-testid="node-detail">
      <div className="row" style={{ gap: 6 }}>
        <Badge tone={tone(node)}>{t(`graph.kind.${node.kind}` as DictKey)}</Badge>
        <span className="xs muted">{graphStatusText(node.status, lang)}</span>
      </div>
      <strong>{label}</strong>
      {node.kind === "gap" && <p className="small">{t("graph.gap_hint")}</p>}
      {node.check_ru && <p className="small"><strong>{t("graph.check")}:</strong> {node.check_ru}</p>}
      {node.excerpt && <blockquote className="small" style={{ margin: 0 }}>{node.excerpt}</blockquote>}
      {node.open?.type === "source" && node.open.source_id && (
        <Button size="sm" onClick={() => setSource(node.open!.source_id!)}>{t("graph.open_page")}</Button>
      )}
      {node.open?.type === "plan" && <Link to="/planner">{t("graph.open_plan")}</Link>}
      {node.open?.type === "decision" && <Link to={`/decisions/${node.open.decision_id}`}>{t("graph.open_decision")}</Link>}
      {(node.open?.type === "calculation" || node.open?.type === "item") && (
        <div className="stack" style={{ gap: 4 }}>
          <span className="xs muted">{t("graph.calc_from")} <code>{node.open.analysis_id?.slice(0, 8)}</code> · <code>{node.open.path}</code>
            {a.data ? <> · {t("header.version")} v{a.data.context.dataset_version} · {a.data.context.method_version}</> : null}</span>
          {a.isLoading && <Loading />}
          {node.open.type === "item" && piece && typeof piece === "object" ? (
            <div className="table-wrap" tabIndex={0}><table className="table xs" data-testid="item-rows">
              <thead><tr><th>{t("graph.option")}</th><th>{t("graph.answer")}</th><th className="num">n</th><th className="num">%</th><th>{t("graph.kind.misconception")}</th></tr></thead>
              <tbody>
                {((piece as { options: { key: string; text: string; correct: boolean; count: number; share: number | null; misconception: string | null }[] }).options).map((o) => (
                  <tr key={o.key}><td>{o.key}{o.correct ? " ✓" : ""}</td><td>{o.text}</td><td className="num">{o.count}</td><td className="num">{pct(o.share, lang)}</td><td className="mono">{o.misconception ?? ""}</td></tr>
                ))}
              </tbody>
            </table></div>
          ) : piece !== undefined ? (
            <pre className="xs json-box" data-testid="calc-json">{JSON.stringify(piece, null, 2)}</pre>
          ) : null}
          {node.open.rules && <span className="xs muted">{Object.entries(node.open.rules).map(([k, v]) => `${k}=${v}`).join(" · ")}</span>}
        </div>
      )}
      {source && <SourceDialog id={source} onClose={() => setSource(null)} />}
    </div>
  );
}
