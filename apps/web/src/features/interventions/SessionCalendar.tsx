/** Planned session calendar of one pilot: draft generation and edits before activation; complete / cancel /
 *  reschedule afterwards (history kept). Class-level data: shown to methodist/approver/teacher only. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { Badge, Button, Card, Field } from "../../ui";
import { useMAction } from "../measurement/api";
import { ActionError, MQuery, useRoles } from "../measurement/components";
import { useMT } from "../measurement/i18n";

type Cal = components["schemas"]["SessionCalendarOut"];
const DAYS = [0, 1, 2, 3, 4, 5];

export function SessionCalendar({ pilotId }: { pilotId: string }) {
  const { t2 } = useMT();
  const { canDraft, canLog } = useRoles();
  const q = useQuery({ queryKey: ["m-sessions", pilotId], queryFn: () => api.get<Cal>(`/api/v1/pilots/${pilotId}/sessions`) });
  const [days, setDays] = useState<number[] | null>(null);
  const [holiday, setHoliday] = useState({ from: "", to: "" });
  const [moves, setMoves] = useState<Record<string, string>>({});
  const gen = useMAction<unknown, Cal>("POST", () => `/api/v1/pilots/${pilotId}/sessions/generate`);
  const patch = useMAction<{ id: string; body: Record<string, unknown> }, Cal>("PATCH", (v) => `/api/v1/pilots/${pilotId}/sessions/${v.id}`, (v) => v.body);
  const del = useMAction<{ id: string }, Cal>("DELETE", (v) => `/api/v1/pilots/${pilotId}/sessions/${v.id}`);
  if (!canLog && !canDraft) return null;
  return (
    <Card title={t2("cal.title")} id="calendar">
      <MQuery q={q}>
        {(c) => {
          const weekdays = days ?? c.default_weekdays;
          return (
            <div className="stack">
              <p className="small muted" style={{ margin: 0 }}>{c.editable ? t2("cal.lead_draft") : t2("cal.lead_active")}</p>
              <p className="small" style={{ margin: 0 }}>{Object.entries(c.counts).map(([k, v]) => `${t2(`cal.status.${k}`)}: ${v}`).join(" · ") || "—"}</p>
              {c.editable && canDraft && (
                <form className="stack" aria-label={t2("cal.generate")} onSubmit={(e) => {
                  e.preventDefault();
                  gen.mutate({ weekdays, blackout_dates: [], blackout_ranges: holiday.from && holiday.to ? [{ from: holiday.from, to: holiday.to }] : [] });
                }}>
                  <fieldset className="row" style={{ border: 0, padding: 0 }}>
                    <legend className="small">{t2("cal.weekdays")}</legend>
                    {DAYS.map((d) => (
                      <label key={d} className="row small" style={{ gap: 4 }}>
                        <input type="checkbox" checked={weekdays.includes(d)}
                          onChange={(e) => setDays(e.target.checked ? [...weekdays, d].sort() : weekdays.filter((x) => x !== d))} /> {t2(`cal.day.${d}`)}
                      </label>
                    ))}
                  </fieldset>
                  <div className="row">
                    <Field label={t2("cal.holiday_from")}>{(id) => <input id={id} className="input" type="date" value={holiday.from} onChange={(e) => setHoliday({ ...holiday, from: e.target.value })} />}</Field>
                    <Field label={t2("cal.holiday_to")}>{(id) => <input id={id} className="input" type="date" value={holiday.to} onChange={(e) => setHoliday({ ...holiday, to: e.target.value })} />}</Field>
                  </div>
                  <Button type="submit" disabled={gen.isPending || weekdays.length === 0}>{t2("cal.generate")}</Button>
                </form>
              )}
              <ActionError error={gen.error || patch.error || del.error} />
              <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto" }}>
                <table className="table" data-testid="calendar">
                  <caption className="sr-only">{t2("cal.title")}</caption>
                  <thead><tr><th scope="col">{t2("fid.date")}</th><th scope="col">{t2("fid.cohort")}</th><th scope="col" className="num">{t2("cal.minutes")}</th>
                    <th scope="col">{t2("common.status")}</th><th scope="col">{t2("common.actions")}</th></tr></thead>
                  <tbody>
                    {c.sessions.map((s) => (
                      <tr key={s.id}>
                        <th scope="row" className="mono">{s.planned_date}</th><td className="mono">{s.cohort_code}</td><td className="num">{s.duration_minutes}</td>
                        <td><Badge tone={s.status === "completed" ? "ok" : s.status === "cancelled" ? "warn" : "neutral"}>{t2(`cal.status.${s.status}`)}</Badge></td>
                        <td>
                          {s.status === "planned" && (
                            <span className="row" style={{ gap: 4 }}>
                              {!c.editable && canLog && <>
                                <Button size="sm" onClick={() => patch.mutate({ id: s.id, body: { status: "completed" } })}>{t2("cal.complete")}</Button>
                                <Button size="sm" onClick={() => patch.mutate({ id: s.id, body: { status: "cancelled" } })}>{t2("cal.cancel")}</Button>
                              </>}
                              {canLog && c.pilot_status !== "completed" && <>
                                <input className="input" type="date" aria-label={`${t2("cal.move_to")} ${s.planned_date} ${s.cohort_code}`} value={moves[s.id] ?? ""}
                                  onChange={(e) => setMoves({ ...moves, [s.id]: e.target.value })} style={{ maxWidth: 160 }} />
                                <Button size="sm" disabled={!moves[s.id]} onClick={() => patch.mutate({ id: s.id, body: { planned_date: moves[s.id] } })}>
                                  {c.editable ? t2("cal.change_date") : t2("cal.reschedule")}
                                </Button>
                              </>}
                              {c.editable && canDraft && <Button size="sm" variant="danger" onClick={() => del.mutate({ id: s.id })}>{t2("cal.delete")}</Button>}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary className="small">{t2("cal.history")} ({c.events.length})</summary>
                <ul className="xs">{c.events.map((e, i) => (
                  <li key={i}>{String(e.at).slice(0, 16).replace("T", " ")} · {t2(`cal.action.${String(e.action)}`)}{e.from_date ? ` ${String(e.from_date)}` : ""}{e.to_date ? ` → ${String(e.to_date)}` : ""}
                    {e.to_status ? ` · ${t2(`cal.status.${String(e.to_status)}`)}` : ""} · {String(e.by ?? (e.source === "fidelity_log" ? t2("cal.by_log") : "—"))}</li>
                ))}</ul>
              </details>
            </div>
          );
        }}
      </MQuery>
    </Card>
  );
}
