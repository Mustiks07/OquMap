import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useComparison, useCurrentDataset, useCurriculum, useGenerate } from "../api/hooks";
import type { ComparisonResult, Envelope, GenerationOut } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { filtersParam, useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, Diff, Disclosure, ErrorState, Field, Loading, ModeBadge, ReasonList, Select, StaleBanner, StatusBadge } from "../ui";
import { GroupedBars } from "../ui/charts";
import { num, pct, pp } from "../ui/format";
import { FilterBar } from "./Filters";
import { NeedDataset } from "./OverviewPage";

export function ComparePage() {
  const { t, lang, pick } = useI18n();
  const st = useAppState();
  const cur = useCurriculum();
  const { dataset } = useCurrentDataset();
  const cmp = useComparison();
  const [scheme, setScheme] = useState("pre_three_level");
  const [weights, setWeights] = useState("pooled");
  const [table, setTable] = useState(false);
  const eds = cur.data?.editions ?? [];
  const a = st.editionA ?? eds[0]?.id ?? null;
  const b = st.editionB ?? eds[1]?.id ?? null;
  const topic = st.topicId ?? cur.data?.topics.find((x) => x.code === "T3")?.id ?? cur.data?.topics[0]?.id ?? null;

  const run = () => {
    if (!st.datasetId || !topic || !a || !b) return;
    cmp.mutate({ dataset_id: st.datasetId, topic_id: topic, edition_a_id: a, edition_b_id: b, filters: st.filters, strata_scheme: scheme, weight_mode: weights, include_topic_table: table },
      { onSuccess: () => st.markStep("compare") });
  };
  useEffect(() => {
    if (dataset?.code === "illustration") {
      setScheme("pre_two_level");
      setWeights("equal");
    }
  }, [dataset?.code]);
  useEffect(run, // eslint-disable-line react-hooks/exhaustive-deps
    [st.datasetId, topic, a, b, scheme, weights, table, filtersParam(st.filters), dataset?.version]);

  if (!st.datasetId) return <NeedDataset />;
  const env = cmp.data as Envelope<ComparisonResult> | undefined;
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t("compare.title")}</h1>
          <p className="muted">{t("compare.lead")}</p>
        </div>
      </div>
      <FilterBar compact />
      <Card>
        <div className="filters">
          <Field label={t("compare.topic")}>
            {(id) => <Select id={id} value={topic ?? ""} onChange={(v) => st.setTopicId(v)} options={(cur.data?.topics ?? []).map((x) => ({ value: x.id, label: `${x.code} ${pick(x, "title")}` }))} />}
          </Field>
          <Field label={t("compare.edition_a")}>
            {(id) => <Select id={id} value={a ?? ""} onChange={(v) => st.setEditions(v, b)} options={eds.map((e) => ({ value: e.id, label: `${e.code} — ${e.title}` }))} />}
          </Field>
          <Field label={t("compare.edition_b")}>
            {(id) => <Select id={id} value={b ?? ""} onChange={(v) => st.setEditions(a, v)} options={eds.map((e) => ({ value: e.id, label: `${e.code} — ${e.title}` }))} />}
          </Field>
          <Field label={t("compare.strata")}>
            {(id) => <Select id={id} value={scheme} onChange={setScheme} options={["pre_three_level", "pre_two_level"].map((v) => ({ value: v, label: t(`compare.strata.${v}` as DictKey) }))} />}
          </Field>
          <Field label={t("compare.weights")}>
            {(id) => <Select id={id} value={weights} onChange={setWeights} options={["pooled", "equal", "arm_a", "arm_b"].map((v) => ({ value: v, label: t(`compare.weights.${v}` as DictKey) }))} />}
          </Field>
          <label className="checkbox"><input type="checkbox" checked={table} onChange={(e) => setTable(e.target.checked)} /> {t("compare.topic_table")}</label>
        </div>
      </Card>
      {cmp.isPending && <Loading />}
      {cmp.isError && <ErrorState error={cmp.error} onRetry={run} />}
      {env && !cmp.isPending && <ComparisonView env={env} />}
      <Illustration />
    </div>
  );

  function ComparisonView({ env }: { env: Envelope<ComparisonResult> }) {
    const r = env.result;
    const ea = r.editions.a as { code: string; title: string };
    const eb = r.editions.b as { code: string; title: string };
    const raw = r.raw as { a: { mean: number | null; n_learners: number; n_classes: number; n_schools: number; n_teachers: number }; b: { mean: number | null; n_learners: number; n_classes: number; n_schools: number; n_teachers: number }; difference: number | null };
    const adj = r.adjusted as { a: number | null; b: number | null; difference: number | null; unavailable_reason: string | null; weights: Record<string, number | null>; strata: { stratum: string; weight: number | null; n_a: number; mean_a: number | null; n_b: number; mean_b: number | null }[] };
    const unc = r.uncertainty as { cluster_unit: string; clusters_per_arm: { a: number; b: number }; adjusted_difference_ci: { low: number; high: number } | null; raw_difference_ci: { low: number; high: number } | null; unavailable_reason: string | null; replicates: number };
    const flip = raw.difference !== null && adj.difference !== null && Math.sign(raw.difference) !== Math.sign(adj.difference);
    const inDraft = st.draft.comparisonAnalysisId === env.context.analysis_id;
    return (
      <>
        <StaleBanner ctx={env.context} onRecompute={run} />
        <Card title={`${r.topic.code as string} · ${ea.code} vs ${eb.code}`} actions={
          <>
            <StatusBadge status={r.status} labelKey={`comparability.${r.status}` as DictKey} />
            <Badge tone={r.inference_level === "adjusted_association" ? "info" : "neutral"}>{t(`inference.${r.inference_level}` as DictKey)}</Badge>
          </>
        }>
          {r.status === "not_comparable" && <Alert tone="danger" title={t("compare.not_comparable")}>{t("compare.not_comparable_body")}</Alert>}
          <div className="grid grid-2" style={{ marginTop: 12 }}>
            <GroupedBars
              title={`${t("compare.raw")} / ${t("compare.adjusted")}`}
              series={[t("compare.raw"), t("compare.adjusted")]}
              data={[
                { label: `${ea.code}`, values: [{ series: t("compare.raw"), value: raw.a.mean, n: raw.a.n_learners }, { series: t("compare.adjusted"), value: adj.a }] },
                { label: `${eb.code}`, values: [{ series: t("compare.raw"), value: raw.b.mean, n: raw.b.n_learners }, { series: t("compare.adjusted"), value: adj.b }] },
              ]}
            />
            <div className="stack">
              <div className="table-wrap" tabIndex={0}>
                <table className="table" data-testid="comparison-table">
                  <thead><tr><th /><th className="num">{ea.code}</th><th className="num">{eb.code}</th><th className="num">{t("compare.difference")}</th></tr></thead>
                  <tbody>
                    <tr><td>{t("compare.raw")}</td><td className="num">{pct(raw.a.mean, lang)}</td><td className="num">{pct(raw.b.mean, lang)}</td><td className="num"><Diff value={raw.difference} /></td></tr>
                    <tr><td>{t("compare.adjusted")}</td><td className="num">{pct(adj.a, lang)}</td><td className="num">{pct(adj.b, lang)}</td><td className="num" data-testid="adjusted-diff"><Diff value={adj.difference} /></td></tr>
                    <tr><td>{t("common.ci95")}</td><td /><td /><td className="num small">{unc.adjusted_difference_ci ? `${pp(unc.adjusted_difference_ci.low, lang)} … ${pp(unc.adjusted_difference_ci.high, lang)}` : <span className="muted">{t("common.ci_unavailable")} ({unc.unavailable_reason})</span>}</td></tr>
                    <tr><td>n: {t("common.learners")} / {t("common.classes")} / {t("common.schools")}</td><td className="num small">{raw.a.n_learners} / {raw.a.n_classes} / {raw.a.n_schools}</td><td className="num small">{raw.b.n_learners} / {raw.b.n_classes} / {raw.b.n_schools}</td><td /></tr>
                  </tbody>
                </table>
              </div>
              <p className="small">{t(`compare.signal.${r.signal}` as DictKey)}</p>
              {flip && <Alert tone="warn">{t("compare.flip")}</Alert>}
              <p className="xs muted">{t("compare.cluster")}: {t(`compare.cluster.${unc.cluster_unit}` as DictKey)} ({unc.clusters_per_arm.a} / {unc.clusters_per_arm.b}); bootstrap ×{unc.replicates}. {t("compare.causal_unavailable")}</p>
              <div className="row">
                <Button variant={inDraft ? "primary" : "default"} aria-pressed={inDraft} data-testid="use-comparison" onClick={() => st.updateDraft({ comparisonAnalysisId: env.context.analysis_id })}>
                  {inDraft ? `✓ ${t("compare.used")}` : t("compare.use_in_decision")}
                </Button>
              </div>
            </div>
          </div>
        </Card>
        <div className="grid grid-2">
          <Card title={t("compare.strata_table")}>
            <div className="table-wrap" tabIndex={0}>
              <table className="table">
                <thead><tr><th /><th className="num">{t("compare.weight")}</th><th className="num">{ea.code} n</th><th className="num">{ea.code}</th><th className="num">{eb.code} n</th><th className="num">{eb.code}</th></tr></thead>
                <tbody>
                  {adj.strata.map((s) => (
                    <tr key={s.stratum}>
                      <td>{t(`compare.${s.stratum}` as DictKey)}</td><td className="num">{pct(s.weight, lang, 0)}</td>
                      <td className="num">{num(s.n_a, lang)}</td><td className="num">{pct(s.mean_a, lang)}</td>
                      <td className="num">{num(s.n_b, lang)}</td><td className="num">{pct(s.mean_b, lang)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="xs muted" style={{ marginTop: 8 }}>adjusted = Σ weight × mean[stratum]; {t("compare.weights")}: {t(`compare.weights.${weights}` as DictKey)}. {adj.unavailable_reason ? `adjusted: ${adj.unavailable_reason}` : ""}</p>
          </Card>
          <Card title={t("compare.reasons")}>
            {r.reasons.length ? <ReasonList reasons={r.reasons} /> : <Alert tone="ok">{t("comparability.comparable")}</Alert>}
            <p className="xs muted" style={{ marginTop: 8 }}>forms: {(r.forms.a ?? []).join(", ")} / {(r.forms.b ?? []).join(", ")}</p>
          </Card>
        </div>
        <Explain analysisId={env.context.analysis_id} />
        {r.topic_table && (
          <Card title={t("compare.topic_table")}>
            <Alert tone="warn">{t("compare.topic_table_note")}</Alert>
            <div className="table-wrap" tabIndex={0} style={{ marginTop: 8 }}>
              <table className="table">
                <thead><tr><th>{t("compare.topic")}</th><th>{t("compare.status")}</th><th className="num">{t("compare.raw")}</th><th className="num">{t("compare.adjusted")}</th><th>{t("common.ci95")}</th></tr></thead>
                <tbody>
                  {(r.topic_table.rows as { topic_id: string; code: string; status: string; raw_difference: number | null; adjusted_difference: number | null; ci: { low: number; high: number } | null }[]).map((row) => (
                    <tr key={row.topic_id}>
                      <td>{row.code}</td><td><StatusBadge status={row.status} labelKey={`comparability.${row.status}` as DictKey} /></td>
                      <td className="num"><Diff value={row.raw_difference} /></td><td className="num"><Diff value={row.adjusted_difference} /></td>
                      <td className="small">{row.ci ? `${pp(row.ci.low, lang)} … ${pp(row.ci.high, lang)}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </>
    );
  }
}

function Explain({ analysisId }: { analysisId: string }) {
  const { t, lang } = useI18n();
  const gen = useGenerate<{ analysis_id: string; lang: string }>("/api/v1/ai/explain-comparison");
  const g = gen.data as GenerationOut | undefined;
  return (
    <Card title={t("compare.explain")} actions={<Button onClick={() => gen.mutate({ analysis_id: analysisId, lang })} disabled={gen.isPending} data-testid="explain-comparison">{t("compare.explain")}</Button>}>
      {gen.isPending && <Loading />}
      {gen.isError && <ErrorState error={gen.error} />}
      {g && (
        <div className="stack">
          <ModeBadge mode={g.mode} fallback={g.fallback_reason} />
          <div className="quote" data-testid="explanation-text">{String(g.output.text ?? "")}</div>
          {Array.isArray(g.output.limitations) && (
            <ul className="small">{(g.output.limitations as string[]).map((x, i) => <li key={i}>{x}</li>)}</ul>
          )}
          <div className="row"><Badge tone={(g.verification as { numbers?: { status: string } }).numbers?.status === "passed" ? "ok" : "danger"}>
            {(g.verification as { numbers?: { status: string } }).numbers?.status === "passed" ? t("ai.verified") : t("ai.unverified")}
          </Badge></div>
        </div>
      )}
    </Card>
  );
}

function Illustration() {
  const { t, lang } = useI18n();
  const q = useQuery({
    queryKey: ["composition-fixture"],
    queryFn: () => api.get<{ fixture: { cells: { arm: string; stratum: string; passed: number; total: number }[] }; raw: { a: { mean: number }; b: { mean: number } }; adjusted: { a: number; b: number } }>("/api/v1/fixtures/composition"),
  });
  return (
    <Card title={t("compare.illustration")}>
      <Disclosure summary={t("common.details")}>
        {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : q.data && (
          <div className="stack">
            <div className="table-wrap" tabIndex={0}>
              <table className="table" data-testid="illustration-table">
                <thead><tr><th /><th className="num">A</th><th className="num">B</th></tr></thead>
                <tbody>
                  {["high", "low"].map((s) => {
                    const ca = q.data.fixture.cells.find((c) => c.arm === "A" && c.stratum === s)!;
                    const cb = q.data.fixture.cells.find((c) => c.arm === "B" && c.stratum === s)!;
                    return (
                      <tr key={s}>
                        <td>{t(`compare.${s}` as DictKey)}</td>
                        <td className="num">{ca.passed} / {ca.total} ({pct(ca.passed / ca.total, lang, 0)})</td>
                        <td className="num">{cb.passed} / {cb.total} ({pct(cb.passed / cb.total, lang, 0)})</td>
                      </tr>
                    );
                  })}
                  <tr><td><strong>{t("compare.overall")}</strong></td><td className="num"><strong>{pct(q.data.raw.a.mean, lang, 0)}</strong></td><td className="num"><strong>{pct(q.data.raw.b.mean, lang, 0)}</strong></td></tr>
                  <tr><td><strong>{t("compare.equal_weights")}</strong></td><td className="num"><strong>{pct(q.data.adjusted.a, lang, 0)}</strong></td><td className="num"><strong>{pct(q.data.adjusted.b, lang, 0)}</strong></td></tr>
                </tbody>
              </table>
            </div>
            <p className="xs muted">{t("compare.illustration_note")}</p>
          </div>
        )}
      </Disclosure>
    </Card>
  );
}
