import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { pollJob, useDatasets, useProject } from "../api/hooks";
import type { DatasetSummary, ImportBatchOut, JobOut } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, ErrorState, Field, Loading, QueryView, Select } from "../ui";
import { num } from "../ui/format";

interface Report {
  rows_total: number;
  rows_accepted: number;
  rows_rejected: number;
  errors_by_code?: Record<string, number>;
  rejected_rows?: { row_number: number; errors: { code: string; field: string | null }[]; values: Record<string, string> }[];
  rejected_rows_truncated?: boolean;
  headers: string[];
  sheets: string[];
  sheet: string | null;
  fields: { required: string[]; optional: string[] };
  preview: Record<string, string>[];
  duplicate_of_batch: string | null;
  available_analysis?: { level: string; possible: string[]; not_possible: string[]; missing_fields: string[] };
  mapping_error?: { missing: string[] };
  commit_allowed?: boolean;
  strict?: boolean;
  blocking?: { code: string; message?: string; dependency?: string }[];
  status_counts?: Record<string, number>;
  new_learners?: number;
  new_classes?: number;
}

const KINDS = ["program", "editions", "item_bank", "roster", "responses", "grades"];

export function ImportWizard({ fixedTarget, onCommitted, kindProp }: { fixedTarget?: "current"; onCommitted?: (j: JobOut) => void; kindProp?: string }) {
  const { t } = useI18n();
  const { datasetId, setDatasetId } = useAppState();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [kindState, setKind] = useState("responses");
  const kind = kindProp ?? kindState;
  const [target, setTarget] = useState<"current" | "new">(fixedTarget ?? (datasetId ? "current" : "new"));
  const [newName, setNewName] = useState("Мой импорт (синтетический)");
  const [batch, setBatch] = useState<ImportBatchOut | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [sheet, setSheet] = useState<string>("");
  const [busy, setBusy] = useState<"" | "validate" | "commit">("");
  const [error, setError] = useState<unknown>(null);
  const [job, setJob] = useState<JobOut | null>(null);

  async function validate(useMapping: boolean) {
    if (!file) return;
    setBusy("validate");
    setError(null);
    setJob(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    if (target === "current" && datasetId) fd.append("dataset_id", datasetId);
    else {
      fd.append("new_dataset_name", newName);
      fd.append("is_synthetic", "true");
    }
    if (sheet) fd.append("sheet", sheet);
    if (useMapping && Object.keys(mapping).length) fd.append("column_mapping", JSON.stringify(mapping));
    try {
      const b = await api.upload<ImportBatchOut>("/api/v1/imports/validate", fd);
      setBatch(b);
      setMapping(b.column_mapping ?? {});
      setSheet(b.sheet ?? "");
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }

  async function commit() {
    if (!batch) return;
    setBusy("commit");
    setError(null);
    try {
      const j0 = await api.post<JobOut>("/api/v1/imports/commit", { batch_id: batch.id });
      const j = await pollJob(j0.id, setJob);
      setJob(j);
      if (j.status === "succeeded") {
        const dsId = (j.result as { dataset_id?: string } | null)?.dataset_id;
        await qc.invalidateQueries();
        if (target === "new" && dsId) setDatasetId(dsId);
        onCommitted?.(j);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }

  const rep = (batch?.report ?? null) as Report | null;
  const allFields = rep ? [...rep.fields.required, ...rep.fields.optional] : [];
  return (
    <div className="stack">
      <Card title={t("import.title")}>
        <div className="filters">
          <Field label={t("import.file")}>
            {(id) => <input id={id} className="input" type="file" accept=".csv,.xlsx,.txt" data-testid="import-file"
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); setBatch(null); setSheet(""); setMapping({}); }} />}
          </Field>
          {!fixedTarget && !kindProp && (
            <Field label={t("import.kind")}>
              {(id) => <Select id={id} value={kind} onChange={setKind} options={KINDS.map((k) => ({ value: k, label: t(`kind.${k}` as DictKey) }))} />}
            </Field>
          )}
          {!fixedTarget && (
            <Field label={t("import.target")}>
              {(id) => (
                <Select id={id} value={target} onChange={(v) => setTarget(v as "current" | "new")}
                  options={[...(datasetId ? [{ value: "current", label: t("import.target.current") }] : []), { value: "new", label: t("import.target.new") }]} />
              )}
            </Field>
          )}
          {target === "new" && (
            <Field label={t("import.new_name")}>
              {(id) => <input id={id} className="input" value={newName} onChange={(e) => setNewName(e.target.value)} />}
            </Field>
          )}
          <Button variant="primary" onClick={() => validate(false)} disabled={!file || busy !== ""} data-testid="import-validate">
            {t("import.validate")}
          </Button>
        </div>
        {!fixedTarget && <p className="xs muted" style={{ marginTop: 8 }}>{t("import.samples")}: <code>followup_2026_2027.csv</code>, <code>upload_sample_with_errors.csv</code>, <code>grades_only_sample.csv</code>. {t("import.samples.note")}</p>}
      </Card>
      {busy === "validate" && <Loading />}
      {error ? <ErrorState error={error} /> : null}
      {batch && rep && (
        <>
          {rep.duplicate_of_batch && <Alert tone="danger" title={t("import.duplicate", { id: rep.duplicate_of_batch.slice(0, 8) })} />}
          {rep.mapping_error && <Alert tone="danger">{t("import.mapping_error", { fields: rep.mapping_error.missing.join(", ") })}</Alert>}
          {rep.blocking && rep.blocking.length > 0 && (
            <Alert tone="danger" title={t("import.blocking")}>
              <ul style={{ margin: 0 }}>{rep.blocking.map((b, i) => <li key={i}>{b.message ?? b.code}</li>)}</ul>
            </Alert>
          )}
          {rep.strict && <Alert tone="info">{t("import.strict")}</Alert>}
          <Card title={t("import.report")} id="import-report">
            <div className="grid grid-3" style={{ marginBottom: 12 }}>
              <div className="metric"><span className="metric-label">{t("import.total")}</span><span className="metric-value">{num(batch.rows_total)}</span></div>
              <div className="metric"><span className="metric-label">{t("import.accepted")}</span><span className="metric-value" style={{ color: "var(--color-ok)" }} data-testid="rows-accepted">{num(batch.rows_accepted)}</span></div>
              <div className="metric"><span className="metric-label">{t("import.rejected")}</span><span className="metric-value" style={{ color: batch.rows_rejected ? "var(--color-danger)" : undefined }} data-testid="rows-rejected">{num(batch.rows_rejected)}</span></div>
            </div>
            <p className="xs muted">sha256 <code>{batch.file_sha256.slice(0, 16)}…</code> · {batch.transform_version} · {batch.filename}</p>
            {rep.errors_by_code && Object.keys(rep.errors_by_code).length > 0 && (
              <>
                <h3>{t("import.errors")}</h3>
                <div className="chip-row" style={{ marginBottom: 12 }}>
                  {Object.entries(rep.errors_by_code).map(([c, n]) => <Badge key={c} tone="danger">{c}: {n}</Badge>)}
                </div>
                <h3>{t("import.rejected_rows")}</h3>
                <div className="table-wrap" style={{ maxHeight: 280 }}>
                  <table className="table">
                    <thead><tr><th>{t("import.row")}</th><th>Ошибки</th><th>Значения</th></tr></thead>
                    <tbody>
                      {rep.rejected_rows?.map((r) => (
                        <tr key={r.row_number}>
                          <td className="num">{r.row_number}</td>
                          <td>{r.errors.map((e, i) => <div key={i}><code>{e.code}</code>{e.field ? ` · ${e.field}` : ""}</div>)}</td>
                          <td className="xs mono">{Object.entries(r.values).filter(([, v]) => v).slice(0, 7).map(([k, v]) => `${k}=${v}`).join("; ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {rep.available_analysis && (
              <div style={{ marginTop: 12 }}>
                <h3>{t("import.available")}</h3>
                <div className="chip-row">
                  {rep.available_analysis.possible.map((p) => <Badge key={p} tone="ok">{p}</Badge>)}
                  {rep.available_analysis.not_possible.map((p) => <Badge key={p} tone="warn">✕ {p}</Badge>)}
                </div>
                {rep.available_analysis.missing_fields.length > 0 && <p className="small" style={{ marginTop: 8 }}>{t("quality.missing")}: <code>{rep.available_analysis.missing_fields.join(", ")}</code></p>}
              </div>
            )}
            <div className="row" style={{ marginTop: 16 }}>
              <Button variant="primary" onClick={commit} disabled={busy !== "" || !!rep.duplicate_of_batch || !!rep.mapping_error || rep.commit_allowed === false || batch.rows_accepted === 0 || job?.status === "succeeded"} data-testid="import-commit">
                {busy === "commit" ? t("import.committing") : t("import.commit")}
              </Button>
              {job && <Badge tone={job.status === "succeeded" ? "ok" : job.status === "failed" ? "danger" : "info"}>{job.status}</Badge>}
            </div>
            {job?.status === "succeeded" && (
              <div style={{ marginTop: 12 }}>
                <Alert tone="ok" title={t("import.committed", { v: String((job.result as { dataset_version?: number })?.dataset_version ?? "") })} />
              </div>
            )}
            {job?.status === "failed" && <div style={{ marginTop: 12 }}><Alert tone="danger" title={String(job.error?.code)}>{String(job.error?.message ?? "")}</Alert></div>}
          </Card>
          <Card title={t("import.mapping")}>
            {rep.sheets.length > 1 && (
              <div style={{ maxWidth: 280, marginBottom: 12 }}>
                <Field label={t("import.sheet")}>
                  {(id) => <Select id={id} value={sheet} onChange={setSheet} options={rep.sheets.map((s) => ({ value: s, label: s }))} />}
                </Field>
              </div>
            )}
            <div className="filters">
              {allFields.map((f) => (
                <Field key={f} label={`${f}${rep.fields.required.includes(f) ? ` (${t("import.mapping.required")})` : ""}`}>
                  {(id) => (
                    <Select id={id} value={mapping[f] ?? ""} onChange={(v) => setMapping((m) => { const n = { ...m }; if (v) n[f] = v; else delete n[f]; return n; })}
                      options={[{ value: "", label: t("import.mapping.none") }, ...rep.headers.map((h) => ({ value: h, label: h }))]} />
                  )}
                </Field>
              ))}
            </div>
            <div style={{ marginTop: 12 }}>
              <Button onClick={() => validate(true)} disabled={busy !== ""}>{t("import.revalidate")}</Button>
            </div>
            <h3 style={{ marginTop: 16 }}>{t("import.preview")}</h3>
            <div className="table-wrap" style={{ maxHeight: 260 }}>
              <table className="table">
                <thead><tr>{rep.headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
                <tbody>{rep.preview.map((r, i) => <tr key={i}>{rep.headers.map((h) => <td key={h} className="xs">{r[h]}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

interface TemplateInfo {
  order: string[];
  rules: string[];
  kinds: { kind: string; strict: boolean; template_csv: string; template_xlsx: string; example_csv: string; fields: { name: string; required: boolean; description: string }[] }[];
}

export function ImportPage() {
  const { t, lang } = useI18n();
  const { datasetId, setDatasetId, user } = useAppState();
  const datasets = useDatasets();
  const project = useProject(datasetId);
  const qc = useQueryClient();
  const templates = useQuery({ queryKey: ["templates"], queryFn: () => api.get<TemplateInfo>("/api/v1/imports/templates"), staleTime: 600_000 });
  const [stage, setStage] = useState<string>("program");
  const [name, setName] = useState("");
  const [synthetic, setSynthetic] = useState(true);
  const [error, setError] = useState<unknown>(null);

  async function createProject() {
    setError(null);
    try {
      const d = await api.post<DatasetSummary>("/api/v1/datasets", { name_ru: name, is_synthetic: synthetic || !!user?.org_is_demo });
      await qc.invalidateQueries({ queryKey: ["datasets"] });
      setDatasetId(d.id);
      setStage("program");
      setName("");
    } catch (e) {
      setError(e);
    }
  }
  return (
    <div className="page stack">
      <div className="page-header">
        <div>
          <h1>{t("project.title")}</h1>
          <p className="muted">{t("project.lead")}</p>
        </div>
      </div>
      <Card>
        <div className="filters">
          <Field label={t("project.select")}>
            {(id) => (
              <Select id={id} value={datasetId ?? ""} onChange={(v) => setDatasetId(v || null)}
                options={[{ value: "", label: "—" }, ...(datasets.data ?? []).map((d) => ({ value: d.id, label: lang === "kz" ? d.name_kz : d.name_ru }))]} />
            )}
          </Field>
          <Field label={t("project.name")}>{(id) => <input id={id} className="input" value={name} onChange={(e) => setName(e.target.value)} data-testid="project-name" />}</Field>
          <label className="checkbox"><input type="checkbox" checked={synthetic || !!user?.org_is_demo} disabled={!!user?.org_is_demo} onChange={(e) => setSynthetic(e.target.checked)} /> {t("project.synthetic")}</label>
          <Button variant="primary" onClick={createProject} disabled={!name.trim()} data-testid="create-project">{t("project.create")}</Button>
        </div>
        {error ? <ErrorState error={error} /> : null}
      </Card>
      {datasetId && (
        <Card title={t("project.stage")}>
          <QueryView q={templates}>
            {(tp) => (
              <div className="stack">
                <ul className="xs muted" style={{ margin: 0 }}>{tp.rules.map((r, i) => <li key={i}>{r}</li>)}</ul>
                <div className="table-wrap">
                  <table className="table" data-testid="stages">
                    <thead><tr><th>{t("project.stage")}</th><th>{t("common.status")}</th><th>Шаблоны</th><th /></tr></thead>
                    <tbody>
                      {tp.kinds.map((k) => {
                        const ps = project.data?.stages.find((x) => x.kind === k.kind);
                        return (
                          <tr key={k.kind} aria-current={stage === k.kind ? "step" : undefined}>
                            <td><strong>{t(`kind.${k.kind}` as DictKey)}</strong>{k.strict && <div className="xs muted">{t("import.strict")}</div>}</td>
                            <td>{ps?.done ? <Badge tone="ok">{t("project.done")}</Badge> : ps?.blocked_message ? <span className="xs" style={{ color: "var(--color-warn)" }}>{ps.blocked_message}</span> : <Badge>{t("project.blocked")}</Badge>}</td>
                            <td className="small">
                              <a href={k.template_xlsx}>{t("project.template_xlsx")}</a> · <a href={k.template_csv}>{t("project.template_csv")}</a> · <a href={k.example_csv}>{t("project.example")}</a>
                            </td>
                            <td><Button size="sm" variant={stage === k.kind ? "primary" : "default"} onClick={() => setStage(k.kind)} data-testid={`stage-${k.kind}`}>{t("project.choose_stage")}</Button></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </QueryView>
        </Card>
      )}
      {datasetId && <ImportWizard key={`${datasetId}-${stage}`} fixedTarget="current" kindProp={stage} onCommitted={() => qc.invalidateQueries({ queryKey: ["project", datasetId] })} />}
      {!datasetId && <ImportWizard />}
    </div>
  );
}
