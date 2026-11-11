import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setToken } from "../api/client";
import { useAiStatus, useOverview } from "../api/hooks";
import type { LoginResponse } from "../api/types";

interface CompareLite {
  status: string; raw: { difference: number | null }; adjusted: { difference: number | null };
  uncertainty: { adjusted_difference_ci: { low: number; high: number } | null }; editions: { a: { code: string }; b: { code: string } };
}
import { useGraph, usePreflight, type Envelope, type IntentPreview, type Quiz, type SandboxResult } from "../api/wow";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, ErrorState, Loading, ModeBadge } from "../ui";
import { pct, pp } from "../ui/format";
import { CouncilPanel } from "./Council";
import { EvidenceGraph, NodeDetail } from "./EvidenceGraph";
import { QuizChecks, QuizItemView } from "./QuizPage";

const STEPS = ["overview", "graph", "compare", "council", "sandbox", "quiz", "decision"] as const;
const KEY = "oqumap.tour.step";

function readStep(): number {
  try {
    const v = Number(sessionStorage.getItem(KEY));
    return Number.isInteger(v) && v >= 0 && v < STEPS.length ? v : 0;
  } catch {
    return 0;
  }
}

/** Read-only presentation: 7 screens, each answers "что обнаружено, почему можно доверять, что делать дальше". */
export function TourPage() {
  const { t } = useI18n();
  const st = useAppState();
  const nav = useNavigate();
  const qc = useQueryClient();
  const pf = usePreflight();
  const ai = useAiStatus();
  const [step, setStep] = useState(readStep);
  const [resetting, setResetting] = useState(false);
  useEffect(() => {
    try { sessionStorage.setItem(KEY, String(step)); } catch { /* ignore */ }
  }, [step]);
  useEffect(() => {
    // A reset replaces the disposable organisation without leaving this route.
    // Reconcile the local step with the value reset before that identity change.
    setStep(readStep());
  }, [st.user?.org_id]);
  useEffect(() => {
    if (pf.data?.topic_id && pf.data.topic_id !== st.topicId) st.setTopicId(pf.data.topic_id);
  }, [pf.data, st]);

  async function reset() {
    setResetting(true);
    try {
      // Reset persisted presentation state before replacing the disposable user.
      // setUser can remount this page, and the new instance must not read the old
      // final step from sessionStorage during that remount.
      try { sessionStorage.setItem(KEY, "0"); } catch { /* ignore */ }
      setStep(0);
      if (st.user?.org_is_ephemeral) {
        // a fresh disposable tenant: identical starting data, nothing left from the previous run
        const r = await api.post<LoginResponse>("/api/v1/auth/demo-login", { persona: "methodist" });
        setToken(r.token);
        st.setUser(r.user);
        if (r.recommended_dataset_id) st.setDatasetId(r.recommended_dataset_id);
      }
      qc.clear();
      setStep(0);
    } finally {
      setResetting(false);
    }
  }

  if (!st.datasetId) return <div className="page"><Alert tone="info">{t("datasets.lead")}</Alert></div>;
  return (
    <div className="page stack tour" data-testid="tour">
      <div className="page-header spread">
        <div>
          <h1>{t("tour.title")}</h1>
          <p className="muted small">{t("tour.lead")}</p>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {ai.data && <ModeBadge mode={ai.data.mode} />}
          <Button size="sm" onClick={reset} disabled={resetting} data-testid="tour-reset">{t("tour.reset")}</Button>
          <Button size="sm" variant="ghost" onClick={() => nav("/overview")}>{t("tour.exit")}</Button>
        </div>
      </div>
      <Preflight q={pf} />
      <nav aria-label={t("tour.steps")} className="tour-steps">
        <ol>
          {STEPS.map((s, i) => (
            <li key={s}>
              <button type="button" className={i === step ? "active" : i < step ? "done" : ""} aria-current={i === step ? "step" : undefined}
                onClick={() => setStep(i)} data-testid={`tour-step-${i + 1}`}>
                <span className="nav-step">{i + 1}</span> {t(`tour.step.${s}` as DictKey)}
              </button>
            </li>
          ))}
        </ol>
      </nav>
      {pf.data?.ready && pf.data.topic_id ? (
        <Step key={STEPS[step]} name={STEPS[step]} topicId={pf.data.topic_id} editions={pf.data.edition_ids ?? []} topicCode={pf.data.topic_code ?? ""} />
      ) : pf.isLoading ? <Loading /> : null}
      <div className="row spread">
        <Button onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0} data-testid="tour-prev">← {t("tour.prev")}</Button>
        <span className="small muted">{step + 1} / {STEPS.length}</span>
        {step < STEPS.length - 1
          ? <Button variant="primary" onClick={() => setStep(step + 1)} data-testid="tour-next">{t("tour.next")} →</Button>
          : <Link className="btn btn-primary" to="/decisions">{t("tour.finish")}</Link>}
      </div>
    </div>
  );
}

function Preflight({ q }: { q: ReturnType<typeof usePreflight> }) {
  const { t } = useI18n();
  if (q.isLoading) return <Loading label={t("tour.preflight_running")} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return null;
  return (
    <details className="small" data-testid="tour-preflight" open={!q.data.ready}>
      <summary>
        {q.data.ready ? <Badge tone="ok">{t("tour.preflight_ok")}</Badge> : <Badge tone="danger">{t("tour.preflight_fail")}</Badge>}{" "}
        <span className="xs muted">{q.data.total_ms} ms</span>
      </summary>
      <ul className="xs">{q.data.checks.map((c) => <li key={c.code}>{c.ok ? "✓" : "✗"} <code>{c.code}</code> {c.ok ? "" : String(c.detail)} · {c.ms} ms</li>)}</ul>
    </details>
  );
}

function Frame({ found, trust, next, children }: { found: ReactNode; trust: ReactNode; next: ReactNode; children?: ReactNode }) {
  const { t } = useI18n();
  return (
    <section className="tour-frame stack">
      <div className="grid grid-3 tour-answers">
        <div data-testid="tour-found"><h3>{t("tour.found")}</h3>{found}</div>
        <div data-testid="tour-trust"><h3>{t("tour.trust")}</h3>{trust}</div>
        <div data-testid="tour-next-action"><h3>{t("tour.next_action")}</h3>{next}</div>
      </div>
      {children}
    </section>
  );
}

function Step({ name, topicId, editions, topicCode }: { name: (typeof STEPS)[number]; topicId: string; editions: string[]; topicCode: string }) {
  switch (name) {
    case "overview": return <OverviewStep topicId={topicId} />;
    case "graph": return <GraphStep topicId={topicId} />;
    case "compare": return <CompareStep topicId={topicId} editions={editions} />;
    case "council": return <CouncilStep topicId={topicId} />;
    case "sandbox": return <SandboxStep topicCode={topicCode} />;
    case "quiz": return <QuizStep topicId={topicId} />;
    default: return <DecisionStep topicId={topicId} />;
  }
}

function OverviewStep({ topicId }: { topicId: string }) {
  const { t, lang, pick } = useI18n();
  const ov = useOverview();
  if (!ov.data) return <Loading />;
  const row = ov.data.result.topics.find((x) => x.topic_id === topicId)!;
  const unmeasured = ov.data.result.topics.filter((x) => !x.score);
  return (
    <Frame
      found={<p><strong>{row.code} {pick(row as unknown as Record<string, unknown>, "title")}</strong> — {pct(row.score?.mean, lang)} {t("tour.overview.found")}</p>}
      trust={<p className="small">{t("tour.overview.trust", { n: row.score?.n_learners ?? 0, c: row.score?.n_classes ?? 0, v: ov.data.context.dataset_version })}
        {unmeasured.length > 0 && <> {t("tour.overview.unmeasured", { codes: unmeasured.map((x) => x.code).join(", ") })}</>}</p>}
      next={<p className="small">{t("tour.overview.next")}</p>}>
      <div className="tour-bars">
        {ov.data.result.topics.map((x) => (
          <div key={x.topic_id} className={`tour-bar${x.topic_id === topicId ? " hl" : ""}`}>
            <span className="mono xs">{x.code}</span>
            <span className="bar"><span style={{ width: `${Math.round((x.score?.mean ?? 0) * 100)}%` }} /></span>
            <span className="xs">{x.score ? pct(x.score.mean, lang) : t(`status.${x.status}` as DictKey)}</span>
          </div>
        ))}
      </div>
    </Frame>
  );
}

function GraphStep({ topicId }: { topicId: string }) {
  const { t, lang } = useI18n();
  const g = useGraph(topicId);
  const [sel, setSel] = useState<string | null>(null);
  if (!g.data) return <Loading />;
  const r = g.data.result;
  const node = r.nodes.find((n) => n.id === sel);
  const labels = r.path.map((id) => r.nodes.find((n) => n.id === id)!).filter((n) => n.kind !== "topic");
  return (
    <Frame
      found={<ol className="small">{labels.map((n) => <li key={n.id}>{lang === "kz" ? n.label_kz : n.label_ru}</li>)}</ol>}
      trust={<p className="small">{t("tour.graph.trust")}</p>}
      next={<p className="small">{t("tour.graph.next", { n: r.gaps.length })}</p>}>
      <div className="graph-layout">
        <EvidenceGraph g={r} selected={sel} onSelect={setSel} pathOnly />
        <div>{node ? <NodeDetail node={node} /> : <p className="small muted">{t("tour.graph.click")}</p>}</div>
      </div>
    </Frame>
  );
}

function CompareStep({ topicId, editions }: { topicId: string; editions: string[] }) {
  const { t, lang } = useI18n();
  const { datasetId } = useAppState();
  const q = useQuery({
    queryKey: ["tour-compare", datasetId, topicId, editions.join()],
    enabled: editions.length === 2,
    queryFn: () => api.post<Envelope<CompareLite>>("/api/v1/comparisons", { dataset_id: datasetId, topic_id: topicId, edition_a_id: editions[0], edition_b_id: editions[1] }),
  });
  if (editions.length < 2) return <Alert tone="info">{t("tour.compare.none")}</Alert>;
  if (!q.data) return <Loading />;
  const r = q.data.result;
  const ci = r.uncertainty.adjusted_difference_ci;
  const flip = r.raw.difference != null && r.adjusted.difference != null && r.raw.difference * r.adjusted.difference < 0;
  return (
    <Frame
      found={<p className="small">{t("tour.compare.found", { a: r.editions.a.code, b: r.editions.b.code, raw: pp(r.raw.difference, lang), adj: pp(r.adjusted.difference, lang) })}
        {flip && <strong> {t("tour.compare.flip")}</strong>}</p>}
      trust={<p className="small">{t("tour.compare.trust")} {ci ? `95% ДИ: ${pp(ci.low, lang)} … ${pp(ci.high, lang)};` : ""} {t(`comparability.${r.status}` as DictKey)}.</p>}
      next={<p className="small">{t("tour.compare.next")}</p>}>
      <div className="grid grid-2">
        <div className="metric"><span className="metric-label">{t("tour.compare.raw")}</span><span className="metric-value" data-testid="tour-raw">{pp(r.raw.difference, lang)}</span></div>
        <div className="metric"><span className="metric-label">{t("tour.compare.adjusted")}</span><span className="metric-value" data-testid="tour-adjusted">{pp(r.adjusted.difference, lang)}</span></div>
      </div>
    </Frame>
  );
}

function CouncilStep({ topicId }: { topicId: string }) {
  const { t } = useI18n();
  return (
    <Frame found={<p className="small">{t("tour.council.found")}</p>} trust={<p className="small">{t("tour.council.trust")}</p>}
      next={<p className="small">{t("tour.council.next")}</p>}>
      <CouncilPanel topicId={topicId} autoRun />
    </Frame>
  );
}

function SandboxStep({ topicCode }: { topicCode: string }) {
  const { t } = useI18n();
  const { datasetId } = useAppState();
  const text = `добавь 2 часа на ${topicCode} за счёт T7`;
  const q = useQuery({
    queryKey: ["tour-sandbox", datasetId, text],
    queryFn: async () => {
      const pv = await api.post<IntentPreview>("/api/v1/sandbox/intent", { dataset_id: datasetId, text });
      const res = await api.post<Envelope<SandboxResult>>("/api/v1/sandbox/run", { dataset_id: datasetId,
        scenarios: [{ name: `A: ${topicCode} +2`, ops: pv.all_ops }, { name: `B: ${topicCode} = 30`, ops: [{ op: "set", topic: topicCode, value: 30 }] }] });
      return { pv, res: res.result };
    },
  });
  if (q.isError) return <ErrorState error={q.error} />;
  if (!q.data) return <Loading />;
  const { pv, res } = q.data;
  const [a, b] = res.scenarios;
  return (
    <Frame
      found={<p className="small">«{text}» → <code>{pv.ops.map((o) => `${o.op} ${o.topic ?? ""} ${o.value ?? ""}`).join("; ")}</code>. {t("tour.sandbox.found", { before: res.before.hours[topicCode], after: a.hours?.[topicCode] ?? "—" })}</p>}
      trust={<p className="small">{t("tour.sandbox.trust")} {b.status === "infeasible" ? t("tour.sandbox.conflict") : ""}</p>}
      next={<p className="small">{t("tour.sandbox.next")}</p>}>
      <table className="table xs" data-testid="tour-sandbox">
        <thead><tr><th /><th className="num">{t("sandbox.before")}</th>{res.scenarios.map((s) => <th key={s.name} className="num">{s.name}</th>)}</tr></thead>
        <tbody>
          {res.topics.map((tp) => (
            <tr key={tp.code}><td>{tp.code}</td><td className="num">{res.before.hours[tp.code]}</td>{res.scenarios.map((s) => <td key={s.name} className="num">{s.hours?.[tp.code] ?? "—"}</td>)}</tr>
          ))}
          <tr><td>{t("sandbox.status")}</td><td />{res.scenarios.map((s) => <td key={s.name} className="num">{s.status_message_ru}</td>)}</tr>
        </tbody>
      </table>
    </Frame>
  );
}

function QuizStep({ topicId }: { topicId: string }) {
  const { t } = useI18n();
  const { datasetId } = useAppState();
  const q = useQuery({ queryKey: ["tour-quiz", datasetId, topicId], queryFn: () => api.post<Quiz>("/api/v1/quizzes/preview", { dataset_id: datasetId, topic_id: topicId, n_items: 3 }) });
  if (q.isError) return <ErrorState error={q.error} />;
  if (!q.data) return <Loading />;
  return (
    <Frame found={<p className="small">{t("tour.quiz.found", { n: q.data.items.length })}</p>} trust={<p className="small">{t("tour.quiz.trust")}</p>}
      next={<p className="small">{t("tour.quiz.next")}</p>}>
      <QuizChecks quiz={q.data} />
      <div className="grid grid-3" data-testid="tour-quiz">
        {q.data.items.map((it) => <QuizItemView key={it.code} it={it} checks={q.data.checks.items[it.code] ?? []} />)}
      </div>
    </Frame>
  );
}

function DecisionStep({ topicId }: { topicId: string }) {
  const { t } = useI18n();
  const g = useGraph(topicId);
  const decided = g.data?.result.nodes.filter((n) => n.kind === "decision") ?? [];
  return (
    <Frame
      found={<p className="small">{decided.length ? t("tour.decision.has", { n: decided.length }) : t("tour.decision.none")}</p>}
      trust={<p className="small">{t("tour.decision.trust")}</p>}
      next={<p className="small">{t("tour.decision.next")}</p>}>
      <ol className="small">
        <li>{t("tour.decision.s1")}</li><li>{t("tour.decision.s2")}</li><li>{t("tour.decision.s3")}</li>
      </ol>
    </Frame>
  );
}
