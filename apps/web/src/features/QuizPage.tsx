import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, download } from "../api/client";
import { useCurriculum } from "../api/hooks";
import { useQuiz, useQuizMutation, useQuizzes, type Quiz, type QuizItem } from "../api/wow";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Loading, Select } from "../ui";
import { pct } from "../ui/format";

const STATUS_TONE = { draft: "neutral", edited: "info", approved: "ok", rejected: "danger", preview: "synthetic" } as const;

/** Diagnostic quiz generator: 3–7 items from observed misconception hypotheses, teacher review, exports, responses. */
export function QuizPage() {
  const { t, pick, lang } = useI18n();
  const st = useAppState();
  const cur = useCurriculum();
  const list = useQuizzes();
  const [topicId, setTopicId] = useState<string>(st.topicId ?? "");
  const [n, setN] = useState("5");
  const [openId, setOpenId] = useState<string | null>(null);
  const [fams, setFams] = useState<string[]>([]);
  const families = useQuery({ queryKey: ["quiz-families"], queryFn: () => api.get<{ code: string; title_ru: string; title_kz: string }[]>("/api/v1/quizzes/families") });
  const gen = useQuizMutation((b: { dataset_id: string; topic_id: string; n_items: number; families: string[] | null }) => api.post<Quiz>("/api/v1/quizzes/generate", b));
  if (!st.datasetId) return <div className="page"><EmptyState>{t("datasets.lead")}</EmptyState></div>;
  const tid = topicId || cur.data?.topics[0]?.id || "";
  return (
    <div className="page stack">
      <div className="page-header">
        <h1>{t("quiz.title")}</h1>
        <p className="muted">{t("quiz.lead")}</p>
      </div>
      <Card title={t("quiz.generate")}>
        <div className="row" style={{ gap: 8 }}>
          <label className="small" htmlFor="quiz-topic">{t("graph.topic")}</label>
          <Select id="quiz-topic" value={tid} onChange={setTopicId}
            options={(cur.data?.topics ?? []).map((x) => ({ value: x.id, label: `${x.code} ${pick(x as unknown as Record<string, unknown>, "title")}` }))} />
          <label className="small" htmlFor="quiz-n">{t("quiz.n_items")}</label>
          <Select id="quiz-n" value={n} onChange={setN} options={["3", "4", "5", "6", "7"].map((v) => ({ value: v, label: v }))} />
          <Button variant="primary" disabled={!tid || gen.isPending} data-testid="quiz-generate"
            onClick={() => gen.mutate({ dataset_id: st.datasetId!, topic_id: tid, n_items: Number(n), families: fams.length ? fams : null }, { onSuccess: (q) => setOpenId(q.id) })}>
            {t("quiz.generate_btn")}
          </Button>
        </div>
        <details className="small" style={{ marginTop: 8 }}>
          <summary>{t("quiz.families")}{fams.length ? ` (${fams.length})` : ""}</summary>
          <p className="xs muted">{t("quiz.families_hint")}</p>
          <div className="row" style={{ gap: 12 }} data-testid="quiz-families">
            {(families.data ?? []).map((f) => (
              <label key={f.code} className="xs row" style={{ gap: 4 }}>
                <input type="checkbox" checked={fams.includes(f.code)} onChange={(e) => setFams(e.target.checked ? [...fams, f.code] : fams.filter((x) => x !== f.code))} />
                {lang === "kz" ? f.title_kz : f.title_ru}
              </label>
            ))}
          </div>
        </details>
        <p className="xs muted">{t("quiz.not_grade")}</p>
        {gen.isError && <ErrorState error={gen.error} />}
      </Card>
      {(list.data ?? []).length > 0 && (
        <Card title={t("quiz.list")}>
          <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {list.data!.map((q) => (
              <li key={q.id} className="row" style={{ gap: 8 }}>
                <button type="button" className="linklike" onClick={() => setOpenId(q.id)}>{q.title}</button>
                <Badge tone={STATUS_TONE[q.status as keyof typeof STATUS_TONE] ?? "neutral"}>{t(`quiz.status.${q.status}` as DictKey)}</Badge>
                <span className="xs muted">v{q.current_version}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {openId && <QuizEditor id={openId} />}
    </div>
  );
}

function QuizEditor({ id }: { id: string }) {
  const { t } = useI18n();
  const q = useQuiz(id);
  const [items, setItems] = useState<QuizItem[] | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const save = useQuizMutation((b: { items: QuizItem[]; note: string }) => api.put<Quiz>(`/api/v1/quizzes/${id}`, b));
  const review = useQuizMutation((b: { action: string; note: string }) => api.post<Quiz>(`/api/v1/quizzes/${id}/review`, b));
  const [upload, setUpload] = useState<{ n_learners: number; summary: { hypotheses: Record<string, { n_learners: number; share: number | null }>; n_rejected: number } } | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <ErrorState error={q.error} />;
  const quiz = q.data;
  const editing = items !== null;
  const shown = items ?? quiz.items;
  const locked = quiz.status === "approved";
  const patch = (i: number, p: Partial<QuizItem>) => setItems(shown.map((it, j) => (j === i ? { ...it, ...p } : it)));
  return (
    <Card title={quiz.title} actions={<Badge tone={STATUS_TONE[quiz.status as keyof typeof STATUS_TONE] ?? "neutral"}>{t(`quiz.status.${quiz.status}` as DictKey)} · v{quiz.current_version}</Badge>}>
      <div data-testid="quiz-editor" className="stack">
        <QuizChecks quiz={quiz} />
        {shown.map((it, i) => (
          <QuizItemView key={it.code} it={it} checks={quiz.checks.items[it.code] ?? []} editing={editing}
            onStem={(v) => patch(i, { stem_ru: v })} onVerify={(v) => patch(i, { teacher_key_verified: v })} />
        ))}
        {err ? <ErrorState error={err} /> : null}
        {!locked && (
          <div className="row">
            {!editing ? <Button onClick={() => setItems(quiz.items.map((x) => ({ ...x })))} data-testid="quiz-edit">{t("quiz.edit")}</Button> : (
              <>
                <input className="input" placeholder={t("quiz.note")} value={note} onChange={(e) => setNote(e.target.value)} aria-label={t("quiz.note")} />
                <Button variant="primary" data-testid="quiz-save" onClick={() => save.mutate({ items: shown, note }, { onSuccess: () => { setItems(null); setNote(""); }, onError: setErr })}>{t("quiz.save_version")}</Button>
                <Button variant="ghost" onClick={() => setItems(null)}>{t("common.cancel")}</Button>
              </>
            )}
            {!editing && (
              <>
                <Button variant="primary" disabled={!quiz.checks.approvable} data-testid="quiz-approve"
                  onClick={() => review.mutate({ action: "approve", note: "" }, { onError: setErr })}>{t("quiz.approve")}</Button>
                <Button variant="danger" onClick={() => review.mutate({ action: "reject", note: "" }, { onError: setErr })}>{t("quiz.reject")}</Button>
              </>
            )}
          </div>
        )}
        <div className="row" style={{ gap: 6 }}>
          <span className="small">{t("quiz.export")}:</span>
          <Button size="sm" onClick={() => download(`/api/v1/quizzes/${id}/export?format=pdf`, "quiz.pdf")}>PDF</Button>
          <Button size="sm" onClick={() => download(`/api/v1/quizzes/${id}/export?format=pdf&teacher=true`, "quiz-teacher.pdf")}>{t("quiz.pdf_teacher")}</Button>
          <Button size="sm" onClick={() => download(`/api/v1/quizzes/${id}/export?format=csv`, "quiz.csv")}>CSV</Button>
          <Button size="sm" onClick={() => download(`/api/v1/quizzes/${id}/export?format=xlsx`, "quiz.xlsx")}>XLSX</Button>
        </div>
        {locked && (
          <div className="stack">
            <label className="small" htmlFor="quiz-resp">{t("quiz.upload_responses")}</label>
            <input id="quiz-resp" type="file" accept=".csv,.xlsx" data-testid="quiz-responses" onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              const fd = new FormData();
              fd.append("file", f);
              try { setUpload(await api.upload(`/api/v1/quizzes/${id}/responses`, fd)); q.refetch(); } catch (x) { setErr(x); }
            }} />
            <span className="xs muted">learner_code,item_code,response · {t("quiz.not_grade")}</span>
            {upload && (
              <Alert tone="info" title={t("quiz.responses_summary", { n: upload.n_learners })}>
                <ul className="small">{Object.entries(upload.summary.hypotheses).map(([k, v]) => <li key={k}><code>{k}</code>: {v.n_learners} ({pct(v.share)})</li>)}</ul>
              </Alert>
            )}
          </div>
        )}
        {quiz.versions && <p className="xs muted">{t("quiz.versions")}: {quiz.versions.map((v) => `v${v.version} (${v.author_kind})`).join(" → ")}</p>}
      </div>
    </Card>
  );
}

export function QuizChecks({ quiz }: { quiz: Pick<Quiz, "checks"> }) {
  const { t } = useI18n();
  return quiz.checks.approvable
    ? <Alert tone="ok" title={t("quiz.checks_ok")}>{t("quiz.checks_ok_hint")}</Alert>
    : <Alert tone="warn" title={t("quiz.checks_failed")}><span className="xs mono" data-testid="quiz-blocking">{quiz.checks.blocking_failed.join(", ")}</span></Alert>;
}

export function QuizItemView({ it, checks, editing = false, onStem, onVerify }: { it: QuizItem; checks: { code: string; passed: boolean; blocking: boolean; detail: string }[]; editing?: boolean; onStem?: (v: string) => void; onVerify?: (v: boolean) => void }) {
  const { t, lang } = useI18n();
  const failed = checks.filter((c) => !c.passed);
  return (
    <section className="quiz-item" aria-label={it.code}>
      <div className="row" style={{ gap: 6 }}>
        <strong>{it.code}</strong>
        <Badge tone="info">{it.objective_code}</Badge>
        <Badge tone="neutral">{t(`quiz.difficulty.${it.difficulty}` as DictKey)}</Badge>
        {it.family ? <Badge tone="ok">{t("quiz.key_exact")}</Badge> : <Badge tone="warn">{t("quiz.key_teacher")}</Badge>}
      </div>
      {editing ? (
        <input className="input" value={it.stem_ru} onChange={(e) => onStem?.(e.target.value)} aria-label={`${it.code} ${t("quiz.stem")}`} />
      ) : <p style={{ margin: "4px 0" }}>{lang === "kz" ? it.stem_kz : it.stem_ru}</p>}
      <ol className="small" type="A" style={{ margin: 0 }}>
        {it.options.map((o) => (
          <li key={o.key}>
            <span className={o.correct ? "strong" : ""}>{o.text}{o.correct ? " ✓" : ""}</span>
            <span className="xs muted"> — {lang === "kz" ? o.rationale_kz : o.rationale_ru}{o.misconception ? ` (${o.misconception})` : ""}</span>
          </li>
        ))}
      </ol>
      <div className="xs muted">{it.evidence_note_ru} · {lang === "kz" ? it.rubric_kz : it.rubric_ru}</div>
      {editing && !it.family && (
        <label className="xs row" style={{ gap: 4 }}>
          <input type="checkbox" checked={!!it.teacher_key_verified} onChange={(e) => onVerify?.(e.target.checked)} data-testid={`verify-${it.code}`} />
          {t("quiz.teacher_verified")}
        </label>
      )}
      {failed.length > 0 && <div className="xs" style={{ color: "var(--color-warn)" }}>{failed.map((c) => `${c.code}${c.detail ? ` (${c.detail})` : ""}`).join("; ")}</div>}
    </section>
  );
}
