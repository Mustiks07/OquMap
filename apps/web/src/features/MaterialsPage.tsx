import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { pollJob, useCurriculum, useDocument, useDocuments, useItemLinks, useReview, useSearch } from "../api/hooks";
import type { FragmentLink, ItemLink, JobOut } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Loading, QueryView, Select, StatusBadge, Tabs } from "../ui";
import { SourceDialog } from "./SourceDialog";

export function MaterialsPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState("documents");
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t("materials.title")}</h1>
          <p className="muted">{t("materials.lead")}</p>
        </div>
      </div>
      <Tabs label={t("materials.title")} active={tab} onChange={setTab}
        tabs={[{ id: "documents", label: t("materials.documents") }, { id: "items", label: t("materials.items") }, { id: "search", label: t("materials.search") }]} />
      {tab === "documents" && <Documents />}
      {tab === "items" && <ItemLinks />}
      {tab === "search" && <Search />}
    </div>
  );
}

function Documents() {
  const { t } = useI18n();
  const docs = useDocuments();
  const cur = useCurriculum();
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (!selected && docs.data?.length) setSelected(docs.data[0].id);
  }, [docs.data, selected]);
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(240px, 320px) 1fr" }}>
      <div className="stack">
        <Card title={t("materials.documents")}>
          <QueryView q={docs} empty={(d) => d.length === 0}>
            {(list) => (
              <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {list.map((d) => {
                  const ed = cur.data?.editions.find((e) => e.id === d.edition_id);
                  return (
                    <li key={d.id}>
                      <button type="button" className={`btn ${selected === d.id ? "btn-primary" : ""}`} style={{ width: "100%", justifyContent: "flex-start", whiteSpace: "normal", textAlign: "left", minHeight: 48 }} onClick={() => setSelected(d.id)} data-testid={`doc-${d.filename}`}>
                        <span>
                          <strong>{ed?.title ?? d.filename}</strong>
                          <br />
                          <span className="xs">{d.filename} · v{d.version} · {d.status}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </QueryView>
        </Card>
        <Upload onUploaded={setSelected} />
      </div>
      {selected ? <DocumentView id={selected} /> : <EmptyState>{t("materials.no_docs")}</EmptyState>}
    </div>
  );
}

function Upload({ onUploaded }: { onUploaded: (id: string) => void }) {
  const { t } = useI18n();
  const cur = useCurriculum();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [edition, setEdition] = useState("");
  const [job, setJob] = useState<JobOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    if (edition) fd.append("edition_id", edition);
    try {
      const r = await api.upload<{ document: { id: string }; job: JobOut }>("/api/v1/documents", fd);
      const j = await pollJob(r.job.id, setJob);
      setJob(j);
      await qc.invalidateQueries({ queryKey: ["documents"] });
      onUploaded(r.document.id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title={t("materials.upload")}>
      <div className="stack">
        <Field label={t("import.file")}>{(id) => <input id={id} type="file" className="input" accept=".pdf,.docx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}</Field>
        <Field label={t("materials.edition")}>
          {(id) => <Select id={id} value={edition} onChange={setEdition} options={[{ value: "", label: "—" }, ...(cur.data?.editions ?? []).map((e) => ({ value: e.id, label: e.title }))]} />}
        </Field>
        <Button variant="primary" onClick={upload} disabled={!file || busy}>{t("materials.upload")}</Button>
        {busy && <Loading label={t("materials.processing")} />}
        {job && <Badge tone={job.status === "succeeded" ? "ok" : job.status === "failed" ? "danger" : "info"}>{job.status}</Badge>}
        {job?.status === "failed" && <Alert tone="danger">{String(job.error?.message ?? "")}</Alert>}
        {error ? <ErrorState error={error} /> : null}
      </div>
    </Card>
  );
}

function DocumentView({ id }: { id: string }) {
  const { t } = useI18n();
  const q = useDocument(id);
  const review = useReview();
  const qc = useQueryClient();
  const [source, setSource] = useState<string | null>(null);
  const [proposing, setProposing] = useState(false);
  return (
    <QueryView q={q}>
      {(d) => {
        const byFrag = new Map<string, FragmentLink[]>();
        d.links.forEach((l) => byFrag.set(l.fragment_id, [...(byFrag.get(l.fragment_id) ?? []), l]));
        const report = d.document.extraction_report as { pages_without_text?: number[] };
        return (
          <Card title={d.document.filename} actions={
            <Button size="sm" disabled={proposing} onClick={async () => {
              setProposing(true);
              try { await api.post(`/api/v1/documents/${id}/propose-links`); await qc.invalidateQueries({ queryKey: ["document", id] }); } finally { setProposing(false); }
            }}>{t("materials.propose")}</Button>
          }>
            <div className="row small" style={{ marginBottom: 8 }}>
              <Badge>v{d.document.version}</Badge>
              <Badge>{d.document.media_type.includes("pdf") ? "PDF" : "DOCX"}</Badge>
              {d.document.page_count != null && <Badge>{d.document.page_count} стр.</Badge>}
              {d.document.is_demo && <Badge tone="synthetic">demo</Badge>}
              <span className="xs muted">sha256 <code>{d.document.sha256.slice(0, 12)}…</code></span>
            </div>
            {d.document.ocr_status === "unavailable" ? (
              <Alert tone="warn">{t("materials.ocr.unavailable")} {report.pages_without_text?.length ? `(стр.: ${report.pages_without_text.join(", ")})` : ""}</Alert>
            ) : (
              <p className="xs muted">{t("materials.ocr.not_needed")} {t("materials.injection_note")}</p>
            )}
            {d.fragments.length === 0 && <EmptyState />}
            <div className="stack" data-testid="fragments">
              {d.fragments.map((f) => (
                <div key={f.id} className="card" style={{ boxShadow: "none", padding: 12 }}>
                  <div className="spread xs muted">
                    <span>
                      {f.page_physical != null ? `${t("materials.page_physical")} ${f.page_physical}` : ""}
                      {f.page_printed ? ` · ${t("materials.page")} ${f.page_printed}` : ""} · {t("materials.anchor")} <code>{f.anchor}</code>
                    </span>
                    <Button size="sm" variant="ghost" onClick={() => setSource(f.id)}>{t("common.open")}</Button>
                  </div>
                  <div className="small" style={{ whiteSpace: "pre-wrap" }}>{f.text}</div>
                  {(byFrag.get(f.id) ?? []).map((l) => (
                    <div key={l.link_id} className="spread" style={{ marginTop: 6, background: "var(--color-surface-muted)", padding: 6, borderRadius: 6 }}>
                      <span className="small">
                        <code>{l.objective_code}</code> {l.objective_text_ru} <Badge>{t(`origin.${l.origin}` as DictKey)}</Badge>
                        {l.rationale && <span className="xs muted"> · {l.rationale}</span>}
                      </span>
                      <span className="row" style={{ gap: 4 }}>
                        <StatusBadge status={l.status} labelKey={`link.${l.status}` as DictKey} />
                        {l.status === "proposed" && (
                          <>
                            <Button size="sm" variant="primary" disabled={review.isPending} data-testid={`confirm-${l.link_id}`} onClick={() => review.mutate({ id: l.link_id, decision: "confirm" })}>{t("materials.confirm")}</Button>
                            <Button size="sm" variant="danger" disabled={review.isPending} onClick={() => review.mutate({ id: l.link_id, decision: "reject" })}>{t("materials.reject")}</Button>
                          </>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            {review.isError && <ErrorState error={review.error} />}
            {source && <SourceDialog id={source} onClose={() => setSource(null)} />}
          </Card>
        );
      }}
    </QueryView>
  );
}

function ItemLinks() {
  const { t } = useI18n();
  const q = useItemLinks();
  const review = useReview();
  const [onlyProposed, setOnlyProposed] = useState(true);
  return (
    <Card title={t("materials.items")}>
      <Alert tone="warn">{t("materials.items_note")}</Alert>
      <label className="checkbox" style={{ margin: "12px 0" }}><input type="checkbox" checked={onlyProposed} onChange={(e) => setOnlyProposed(e.target.checked)} /> {t("link.proposed")}</label>
      <QueryView q={q}>
        {(d) => {
          const rows = d.item_links.filter((l: ItemLink) => !onlyProposed || l.status === "proposed");
          if (!rows.length) return <EmptyState />;
          return (
            <div className="table-wrap" tabIndex={0}>
              <table className="table">
                <thead><tr><th>Задание</th><th>Цель</th><th className="num">Вес</th><th>Источник</th><th>{t("common.status")}</th><th /></tr></thead>
                <tbody>
                  {rows.map((l) => (
                    <tr key={l.link_id}>
                      <td><code>{l.item_code}</code> <span className="small">{l.stem_ru}</span></td>
                      <td><code>{l.objective_code}</code> <span className="xs">{l.objective_text_ru}</span></td>
                      <td className="num">{l.weight.toFixed(2)}</td>
                      <td className="xs">{t(`origin.${l.origin}` as DictKey)}</td>
                      <td><StatusBadge status={l.status} labelKey={`link.${l.status}` as DictKey} /></td>
                      <td className="row" style={{ gap: 4 }}>
                        {l.status === "proposed" && (
                          <>
                            <Button size="sm" variant="primary" disabled={review.isPending} onClick={() => review.mutate({ id: l.link_id, decision: "confirm" })}>{t("materials.confirm")}</Button>
                            <Button size="sm" variant="danger" disabled={review.isPending} onClick={() => review.mutate({ id: l.link_id, decision: "reject" })}>{t("materials.reject")}</Button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </QueryView>
    </Card>
  );
}

function Search() {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const res = useSearch(q);
  const [source, setSource] = useState<string | null>(null);
  return (
    <Card title={t("materials.search")}>
      <form className="row" onSubmit={(e) => { e.preventDefault(); setQ(text); }}>
        <label className="sr-only" htmlFor="search-q">{t("materials.search")}</label>
        <input id="search-q" className="input" style={{ maxWidth: 520 }} value={text} placeholder={t("materials.search_ph")} onChange={(e) => setText(e.target.value)} />
        <Button type="submit" variant="primary">{t("materials.search")}</Button>
      </form>
      <div style={{ marginTop: 12 }}>
        {res.isFetching && <Loading />}
        {res.isError && <ErrorState error={res.error} onRetry={() => res.refetch()} />}
        {res.data && (res.data.results.length === 0 ? <EmptyState /> : (
          <ul className="stack" style={{ listStyle: "none", padding: 0 }}>
            {res.data.results.map((r) => (
              <li key={r.source_id} className="card" style={{ boxShadow: "none" }}>
                <div className="spread small">
                  <span><strong>{r.edition_code ?? r.document_filename}</strong> v{r.document_version} · {r.page_printed ? `${t("materials.page")} ${r.page_printed}` : `${t("materials.anchor")} ${r.anchor}`}</span>
                  <Button size="sm" onClick={() => setSource(r.source_id)}>{t("common.open")}</Button>
                </div>
                <div className="quote">{r.excerpt}</div>
                <div className="xs muted">{t("materials.matched")}: {r.relevance.matched_terms.join(", ")} · score {r.score}</div>
              </li>
            ))}
          </ul>
        ))}
      </div>
      {source && <SourceDialog id={source} onClose={() => setSource(null)} />}
    </Card>
  );
}
