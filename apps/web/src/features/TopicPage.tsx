import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useGenerate, useTopicEvidence } from "../api/hooks";
import type { GenerationOut, ItemEvidence, Misconception, TopicEvidenceResult } from "../api/types";
import { useI18n } from "../i18n/I18n";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, CI, Card, Disclosure, EmptyState, ErrorState, Metric, ModeBadge, QueryView, ShareBar, StaleBanner, StatusBadge } from "../ui";
import { num, pct } from "../ui/format";
import { FilterBar } from "./Filters";
import { NeedDataset } from "./OverviewPage";
import { SourceDialog } from "./SourceDialog";

export function TopicPage() {
  const { t, lang, pick } = useI18n();
  const params = useParams();
  const { datasetId, topicId, setTopicId, updateDraft, draft, markStep } = useAppState();
  const id = params.topicId ?? topicId;
  useEffect(() => {
    if (params.topicId && params.topicId !== topicId) setTopicId(params.topicId);
  }, [params.topicId, topicId, setTopicId]);
  const q = useTopicEvidence(id ?? null);
  const nav = useNavigate();
  const [source, setSource] = useState<string | null>(null);
  useEffect(() => {
    if (q.data && !q.data.context.is_stale) {
      updateDraft({ topicAnalysisId: q.data.context.analysis_id });
      markStep("topic");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data?.context.analysis_id]);
  if (!datasetId) return <NeedDataset />;
  if (!id) return <EmptyState>{t("topic.select")}</EmptyState>;
  return (
    <div className="page stack">
      <FilterBar compact />
      <QueryView q={q}>
        {(env) => {
          const r: TopicEvidenceResult = env.result;
          const s = r.summary;
          return (
            <>
              <StaleBanner ctx={env.context} onRecompute={() => q.refetch()} />
              <div className="page-header">
                <div>
                  <h1 data-testid="topic-title">{r.topic.code as string} · {pick(r.topic as Record<string, unknown>, "title")}</h1>
                  <div className="row"><StatusBadge status={r.status} /> <span className="xs muted">analysis <code>{env.context.analysis_id.slice(0, 8)}</code> · data v{env.context.dataset_version}</span></div>
                </div>
                <div className="row">
                  <Button onClick={() => nav("/compare")} variant="primary">{t("topic.to_compare")}</Button>
                  <Button onClick={() => nav("/planner")}>{t("topic.to_plan")}</Button>
                </div>
              </div>
              <Card title={t("topic.summary")}>
                {s ? (
                  <div className="grid grid-4">
                    <Metric label={t("overview.score")} value={<span data-testid="topic-score">{pct(s.mean, lang)}</span>} sub={<CI low={s.ci_low} high={s.ci_high} reason={s.ci_unavailable_reason} />} />
                    <Metric label={t("common.learners")} value={num(s.n_learners, lang)} sub={`${s.n_classes} ${t("common.classes")} · ${s.n_schools} ${t("common.schools")}`} />
                    <Metric label={t("topic.absent")} value={num(r.exclusions.absent_sittings, lang)} sub={`${t("topic.omitted")}: ${num(r.exclusions.omitted_responses, lang)}`} />
                    <Metric label={t("topic.retakes")} value={num(r.exclusions.learners_with_repeat_attempts, lang)} sub={`${t("filters.attempt")}: ${t(`filters.attempt.${r.rules.attempt_rule}` as never)}`} />
                  </div>
                ) : (
                  <Alert tone="warn" title={t(`status.${r.status}` as never)}>{t("bands.note")}</Alert>
                )}
                <p className="xs muted" style={{ marginTop: 8 }}>{t("common.share_note")} {s?.ci_method ? `CI: ${s.ci_method}` : ""}</p>
              </Card>
              <div className="grid grid-2">
                <Card title={t("topic.objectives")}>
                  <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                    {r.objectives.map((o) => (
                      <li key={o.objective_id}>
                        <div className="spread"><span><code>{o.code}</code> {pick(o, "text")}</span><StatusBadge status={o.status} /></div>
                        {o.score ? <ShareBar value={o.score.mean} label={o.code} /> : null}
                        <span className="xs muted">{o.n_items_confirmed} {t("topic.n_items_conf")} · {o.n_items_proposed} {t("topic.n_items_prop")}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
                <Card title={t("topic.prereq")}>
                  {r.prerequisites.length === 0 ? <EmptyState /> : (
                    <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                      {r.prerequisites.map((p) => (
                        <li key={p.objective_id as string}>
                          <div><code>{p.code as string}</code> ({p.topic_code as string}) {pick(p as Record<string, unknown>, "text")} → <code>{p.target_code as string}</code></div>
                          {p.score ? <ShareBar value={(p.score as { mean: number }).mean} /> : <span className="xs muted">{t("status.not_measured")}</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
              <Misconceptions r={r} analysisId={env.context.analysis_id} />
              <Card title={t("topic.items")}>
                <div className="stack">
                  {r.items.map((it) => <ItemRow key={it.item_id} it={it} />)}
                  {r.items.length === 0 && <EmptyState />}
                </div>
              </Card>
              <div className="grid grid-2">
                <Card title={t("topic.sources")}>
                  {r.sources.length === 0 ? <p className="small muted">{t("topic.no_sources")}</p> : (
                    <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                      {r.sources.map((src) => {
                        const inDraft = draft.sourceIds.includes(src.source_id);
                        return (
                          <li key={src.link_id} className="stack" style={{ gap: 4 }}>
                            <div className="spread">
                              <span className="small"><strong>{src.edition_code}</strong> {src.page_printed ? `${t("materials.page")} ${src.page_printed}` : `${t("materials.anchor")} ${src.anchor}`} · <code>{src.objective_code}</code></span>
                              <span className="row" style={{ gap: 4 }}>
                                <StatusBadge status={src.status} labelKey={`link.${src.status}` as never} />
                                <Button size="sm" onClick={() => setSource(src.source_id)}>{t("common.open")}</Button>
                                <Button size="sm" variant={inDraft ? "primary" : "default"} aria-pressed={inDraft}
                                  onClick={() => updateDraft({ sourceIds: inDraft ? draft.sourceIds.filter((x) => x !== src.source_id) : [...draft.sourceIds, src.source_id] })}>
                                  {inDraft ? "✓" : "+"} {t("nav.decision")}
                                </Button>
                              </span>
                            </div>
                            <div className="quote">{src.excerpt}</div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </Card>
                <Card title={t("topic.classes")}>
                  <div className="table-wrap" tabIndex={0} style={{ maxHeight: 360 }}>
                    <table className="table">
                      <thead><tr><th>Класс</th><th>Школа</th><th>Издание</th><th className="num">n</th><th>{t("overview.score")}</th></tr></thead>
                      <tbody>
                        {r.classes.map((c) => (
                          <tr key={c.cohort_id as string}>
                            <td className="mono small">{c.code as string}</td><td className="small">{c.school_code as string}</td><td className="small">{(c.edition_code as string) ?? "—"}</td>
                            <td className="num">{c.n as number}</td><td><ShareBar value={c.mean as number} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
              {source && <SourceDialog id={source} onClose={() => setSource(null)} />}
            </>
          );
        }}
      </QueryView>
    </div>
  );
}

function ItemRow({ it }: { it: ItemEvidence }) {
  const { t, lang } = useI18n();
  return (
    <div className="card" style={{ boxShadow: "none" }}>
      <div className="spread">
        <span><code>{it.code}</code> {lang === "kz" ? it.stem_kz : it.stem_ru}</span>
        <span className="row small" style={{ gap: 6 }}>
          {it.objectives.map((o) => <Badge key={o.link_id as string} tone={o.status === "confirmed" ? "ok" : "warn"}>{o.code as string} ×{Number(o.weight).toFixed(2)}</Badge>)}
        </span>
      </div>
      <div className="row small" style={{ margin: "6px 0" }}>
        <span>{t("topic.p_correct")}: <strong>{pct(it.p_correct, lang)}</strong> (n={it.n_answered})</span>
        <span>{t("topic.omit_rate")}: {pct(it.omit_rate, lang)} ({it.n_omitted})</span>
        <span className="muted">{t("topic.weight")}: {it.topic_weight.toFixed(2)}</span>
      </div>
      <div className="table-wrap" tabIndex={0}>
        <table className="table">
          <tbody>
            {it.options.map((o) => (
              <tr key={o.key}>
                <td style={{ width: 30 }} className={o.correct ? "option-correct" : ""}>{o.key}{o.correct ? " ✓" : ""}</td>
                <td className={o.correct ? "option-correct" : ""} style={{ width: 140 }}>{o.text}</td>
                <td style={{ width: 220 }}><ShareBar value={o.share} label={o.key} /></td>
                <td className="xs muted">{o.misconception ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Misconceptions({ r, analysisId }: { r: TopicEvidenceResult; analysisId: string }) {
  const { t, lang } = useI18n();
  const gen = useGenerate<{ analysis_id: string; code: string; lang: string }>("/api/v1/ai/interpret-misconception");
  const [result, setResult] = useState<Record<string, GenerationOut>>({});
  return (
    <Card title={t("topic.misconceptions")}>
      <p className="xs muted">{t("topic.hypothesis_note")}</p>
      {r.misconceptions.length === 0 ? <EmptyState /> : (
        <div className="stack">
          {r.misconceptions.slice(0, 5).map((m: Misconception) => (
            <div key={m.code} className="card" style={{ boxShadow: "none" }}>
              <div className="spread">
                <strong>{lang === "kz" ? m.label_kz : m.label_ru}</strong>
                <span className="small">{num(m.n_learners, lang)} {t("common.learners")} ({pct(m.share_of_learners, lang)}) · {m.items.join(", ")}</span>
              </div>
              <div className="small"><span className="muted">{t("topic.check")}:</span> {m.diagnostic_check_ru}</div>
              <div className="row" style={{ marginTop: 6 }}>
                <Button size="sm" disabled={gen.isPending} data-testid={`interpret-${m.code}`}
                  onClick={() => gen.mutate({ analysis_id: analysisId, code: m.code, lang }, { onSuccess: (g) => setResult((x) => ({ ...x, [m.code]: g })) })}>
                  {t("topic.interpret")}
                </Button>
              </div>
              {result[m.code] && (
                <div className="stack" style={{ marginTop: 8 }}>
                  <ModeBadge mode={result[m.code].mode} fallback={result[m.code].fallback_reason} />
                  <div className="quote">{String(result[m.code].output.interpretation ?? "")}</div>
                  <Disclosure summary={t("common.details")}><pre className="xs mono" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(result[m.code].verification, null, 1)}</pre></Disclosure>
                </div>
              )}
            </div>
          ))}
          {gen.isError && <ErrorState error={gen.error} />}
        </div>
      )}
    </Card>
  );
}
