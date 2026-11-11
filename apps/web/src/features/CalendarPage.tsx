import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useI18n } from "../i18n/I18n";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Loading } from "../ui";

type Sched = Record<string, Record<string, number>>;
interface Reason { code: string; text_ru: string; text_kz: string }
interface Move { topic: string; moved: boolean; current: { start: number; end: number } | null; proposed: { start: number; end: number } | null;
  hours: { current: number; proposed: number }; reasons: Reason[] }
interface CalContext {
  defaults: { start_date: string; n_weeks: number; weekly_hours: number; unavailable_weeks: number[] };
  topics: { code: string; title_ru: string; title_kz: string; hours: number; status: string | null }[];
  prerequisites: { before: string; topic: string }[]; current: Sched; note_ru: string;
}
interface CalResult {
  status: string; weeks: { index: number; start: string }[]; capacity: number[]; unavailable_weeks: number[];
  current: Sched; proposed: Sched | null; load: { week: number; capacity: number; unavailable: boolean; current: number; proposed: number }[] | null;
  moves: Move[]; validation: { valid: boolean } | null; note_ru: string;
  conflict: { verified: boolean; constraints: { key: string; message_ru: string; message_kz: string }[]; arithmetic: { message_ru: string } | null } | null;
}
interface Fixed { topic: string; from_week: number | null; to_week: number | null }

const parseWeeks = (s: string) => Array.from(new Set(s.split(/[,\s]+/).map(Number).filter((n) => Number.isInteger(n) && n > 0))).sort((a, b) => a - b);

/** Weekly calendar: topics by week with weekly load, prerequisites, fixed windows and holidays; current vs proposed. */
export function CalendarPage() {
  const { t, lang } = useI18n();
  const st = useAppState();
  const ctx = useQuery({ queryKey: ["calendar-context", st.datasetId], enabled: !!st.datasetId,
    queryFn: () => api.get<CalContext>("/api/v1/calendar/context", { dataset_id: st.datasetId! }) });
  const [weekly, setWeekly] = useState(4);
  const [nWeeks, setNWeeks] = useState(34);
  const [start, setStart] = useState("2026-08-31");
  const [holidays, setHolidays] = useState("");
  const [keepOrder, setKeepOrder] = useState(true);
  const [usePlan, setUsePlan] = useState(!!st.draft.planAnalysisId);
  const [hours, setHours] = useState<Record<string, string>>({});
  const [fixed, setFixed] = useState<Fixed[]>([]);
  useEffect(() => {
    if (ctx.data) {
      setWeekly(ctx.data.defaults.weekly_hours); setNWeeks(ctx.data.defaults.n_weeks); setStart(ctx.data.defaults.start_date);
      setHolidays(ctx.data.defaults.unavailable_weeks.join(", "));
    }
  }, [ctx.data]);
  const solve = useMutation({
    mutationFn: () => api.post<{ context: { analysis_id: string }; result: CalResult }>("/api/v1/calendar/solve", {
      dataset_id: st.datasetId, start_date: start, n_weeks: nWeeks, weekly_hours: weekly, unavailable_weeks: parseWeeks(holidays),
      keep_order: keepOrder, fixed: fixed.filter((f) => f.topic),
      topic_hours: Object.fromEntries(Object.entries(hours).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)])),
      plan_analysis_id: usePlan ? st.draft.planAnalysisId : null, plan_preset: st.draft.planPreset ?? "balanced",
    }),
  });
  if (!st.datasetId) return <div className="page"><EmptyState>{t("datasets.lead")}</EmptyState></div>;
  if (ctx.isLoading) return <Loading />;
  if (ctx.isError || !ctx.data) return <ErrorState error={ctx.error} onRetry={() => ctx.refetch()} />;
  const c = ctx.data;
  const r = solve.data?.result;
  return (
    <div className="page stack">
      <div className="page-header">
        <h1>{t("calendar.title")}</h1>
        <p className="muted">{t("calendar.lead")}</p>
      </div>
      <Card title={t("calendar.settings")}>
        <div className="filters">
          <label className="small stack" style={{ gap: 2 }}>{t("calendar.start")}<input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label className="small stack" style={{ gap: 2 }}>{t("calendar.weeks")}<input className="input" type="number" min={1} max={45} value={nWeeks} onChange={(e) => setNWeeks(Number(e.target.value))} /></label>
          <label className="small stack" style={{ gap: 2 }}>{t("calendar.weekly")}<input className="input" type="number" min={0} max={40} value={weekly} onChange={(e) => setWeekly(Number(e.target.value))} data-testid="cal-weekly" /></label>
          <label className="small stack" style={{ gap: 2 }}>{t("calendar.holidays")}<input className="input" value={holidays} onChange={(e) => setHolidays(e.target.value)} data-testid="cal-holidays" /></label>
        </div>
        <div className="row" style={{ gap: 16, marginTop: 8 }}>
          <label className="small row" style={{ gap: 4 }}><input type="checkbox" checked={keepOrder} onChange={(e) => setKeepOrder(e.target.checked)} />{t("calendar.keep_order")}</label>
          {st.draft.planAnalysisId && (
            <label className="small row" style={{ gap: 4 }}><input type="checkbox" checked={usePlan} onChange={(e) => setUsePlan(e.target.checked)} data-testid="cal-use-plan" />
              {t("calendar.use_plan")} <code>{st.draft.planAnalysisId.slice(0, 8)}</code></label>
          )}
        </div>
        <details className="small" style={{ marginTop: 8 }}>
          <summary>{t("calendar.topics_hours")}</summary>
          <table className="table xs">
            <thead><tr><th>{t("sandbox.topic")}</th><th className="num">{t("calendar.plan_hours")}</th><th>{t("calendar.override")}</th><th>{t("calendar.fixed")}</th></tr></thead>
            <tbody>
              {c.topics.map((tp) => {
                const f = fixed.find((x) => x.topic === tp.code);
                const setF = (patch: Partial<Fixed>) => setFixed([...fixed.filter((x) => x.topic !== tp.code), { topic: tp.code, from_week: f?.from_week ?? null, to_week: f?.to_week ?? null, ...patch }]);
                return (
                  <tr key={tp.code}>
                    <td>{tp.code} {lang === "kz" ? tp.title_kz : tp.title_ru}</td>
                    <td className="num">{tp.hours}</td>
                    <td><input className="input" style={{ width: 72 }} type="number" min={0} aria-label={`${tp.code} ${t("calendar.override")}`} value={hours[tp.code] ?? ""}
                      onChange={(e) => setHours({ ...hours, [tp.code]: e.target.value })} data-testid={`cal-hours-${tp.code}`} /></td>
                    <td className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                      <input className="input" style={{ width: 60 }} type="number" min={1} aria-label={`${tp.code} ${t("calendar.from")}`} value={f?.from_week ?? ""}
                        onChange={(e) => setF({ from_week: e.target.value ? Number(e.target.value) : null })} data-testid={`cal-from-${tp.code}`} />–
                      <input className="input" style={{ width: 60 }} type="number" min={1} aria-label={`${tp.code} ${t("calendar.to")}`} value={f?.to_week ?? ""}
                        onChange={(e) => setF({ to_week: e.target.value ? Number(e.target.value) : null })} data-testid={`cal-to-${tp.code}`} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="xs muted">{t("calendar.prereqs")}: {c.prerequisites.map((p) => `${p.before}→${p.topic}`).join(", ")}</p>
        </details>
        <div className="row" style={{ marginTop: 8 }}>
          <Button variant="primary" onClick={() => solve.mutate()} disabled={solve.isPending} data-testid="cal-solve">{t("calendar.solve")}</Button>
          <span className="xs muted">{c.note_ru}</span>
        </div>
      </Card>
      {solve.isPending && <Loading />}
      {solve.isError && <ErrorState error={solve.error} />}
      {r?.conflict && (
        <Alert tone="danger" title={t("calendar.conflict")}>
          <div data-testid="cal-conflict">
            <ul className="small">{r.conflict.constraints.map((x) => <li key={x.key}>{lang === "kz" ? x.message_kz : x.message_ru}</li>)}</ul>
            {r.conflict.arithmetic && <p className="small"><strong>{r.conflict.arithmetic.message_ru}</strong></p>}
            <p className="xs">{r.conflict.verified ? t("calendar.conflict_verified") : ""}</p>
          </div>
        </Alert>
      )}
      <Card title={r?.proposed ? t("calendar.compare") : t("calendar.current")}>
        <Gantt topics={c.topics.map((x) => x.code)} current={r?.current ?? c.current} proposed={r?.proposed ?? null}
          nWeeks={r ? r.capacity.length : c.defaults.n_weeks} unavailable={r ? r.unavailable_weeks : c.defaults.unavailable_weeks} load={r?.load ?? null} />
        {r?.validation?.valid && <p className="xs muted">{t("sandbox.validator")}: ✓ · {r.note_ru}</p>}
      </Card>
      {r && r.moves.length > 0 && (
        <Card title={t("calendar.moves")}>
          <div className="table-wrap" tabIndex={0}>
            <table className="table" data-testid="cal-moves">
              <thead><tr><th>{t("sandbox.topic")}</th><th>{t("sandbox.was")}</th><th>{t("sandbox.becomes")}</th><th>{t("calendar.why")}</th></tr></thead>
              <tbody>
                {r.moves.map((mv) => (
                  <tr key={mv.topic} className={mv.moved ? "" : "muted"}>
                    <td>{mv.topic}</td>
                    <td className="small">{mv.current ? `${t("calendar.wk")} ${mv.current.start}–${mv.current.end}` : "—"} · {mv.hours.current} ч</td>
                    <td className="small">{mv.proposed ? `${t("calendar.wk")} ${mv.proposed.start}–${mv.proposed.end}` : "—"} · {mv.hours.proposed} ч</td>
                    <td className="small">{mv.reasons.map((x) => (lang === "kz" ? x.text_kz : x.text_ru)).join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function Gantt({ topics, current, proposed, nWeeks, unavailable, load }: { topics: string[]; current: Sched; proposed: Sched | null; nWeeks: number;
  unavailable: number[]; load: CalResult["load"] }) {
  const { t } = useI18n();
  const weeks = useMemo(() => Array.from({ length: nWeeks }, (_, i) => i + 1), [nWeeks]);
  const hol = new Set(unavailable);
  const row = (code: string, s: Sched, kind: "cur" | "new") => (
    <tr key={`${code}-${kind}`} className={kind === "new" ? "gantt-new" : "gantt-cur"}>
      <th scope="row" className="xs">{code} <span className="muted">{kind === "cur" ? t("sandbox.was") : t("sandbox.becomes")}</span></th>
      {weeks.map((w) => {
        const h = s[code]?.[String(w)];
        return <td key={w} className={`gantt-cell${hol.has(w) ? " hol" : ""}${h ? " on" : ""}`} title={h ? `${code}: ${h} ч, ${t("calendar.wk")} ${w}` : undefined}>{h ?? ""}</td>;
      })}
    </tr>
  );
  return (
    <div className="table-wrap gantt" tabIndex={0} data-testid="cal-gantt">
      <table className="table xs">
        <thead><tr><th />{weeks.map((w) => <th key={w} className={`num${hol.has(w) ? " hol" : ""}`} title={hol.has(w) ? t("calendar.holiday") : undefined}>{w}</th>)}</tr></thead>
        <tbody>
          {topics.flatMap((code) => (proposed ? [row(code, current, "cur"), row(code, proposed, "new")] : [row(code, current, "cur")]))}
          {load && (
            <tr className="metric-row" data-testid="cal-load">
              <th scope="row" className="xs">{t("calendar.load")}</th>
              {load.map((l) => <td key={l.week} className={`gantt-cell${l.unavailable ? " hol" : ""}`} title={`${l.proposed}/${l.capacity}`}>{l.unavailable ? "—" : `${l.proposed}`}</td>)}
            </tr>
          )}
        </tbody>
      </table>
      <div className="row xs" style={{ gap: 8, padding: 6 }}>
        <Badge tone="neutral">{t("calendar.legend_hol")}</Badge><span className="muted">{t("calendar.legend_cells")}</span>
      </div>
    </div>
  );
}
