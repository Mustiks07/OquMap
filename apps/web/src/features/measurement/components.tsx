/** Small presentation helpers shared by the measurement screens (no business logic: all statuses and texts come
 *  from the server). */
import type { ReactNode } from "react";
import { ApiError } from "../../api/client";
import { useAppState } from "../../state/AppState";
import { Alert, Badge, ErrorState, Loading, type Tone } from "../../ui";
import { num, pct, pp } from "../../ui/format";
import { useMT } from "./i18n";
import type { Label, Message } from "./api";

export function hasRole(roles: string[] | undefined, ...need: string[]): boolean {
  const r = roles ?? [];
  return r.includes("admin") || need.some((n) => r.includes(n));
}

export function useRoles() {
  const { user } = useAppState();
  const roles = user?.roles ?? [];
  return {
    roles,
    canDraft: hasRole(roles, "methodist"),
    canApprove: hasRole(roles, "approver"),
    canLog: hasRole(roles, "methodist", "teacher"),
  };
}

/** Error view that distinguishes "forbidden" from other failures. */
export function MError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t2 } = useMT();
  if (error instanceof ApiError && error.status === 403) {
    return (
      <Alert tone="warn" title={t2("common.forbidden")} role="alert">
        <span className="small">{t2("common.forbidden_hint")}</span>
      </Alert>
    );
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}

export function MQuery<T>({ q, empty, emptyText, children }: {
  q: { isLoading: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown };
  empty?: (d: T) => boolean; emptyText?: ReactNode; children: (d: T) => ReactNode;
}) {
  const { t } = useMT();
  if (q.isLoading) return <Loading />;
  if (q.isError) return <MError error={q.error} onRetry={() => q.refetch()} />;
  if (q.data === undefined || (empty && empty(q.data))) return <div className="state">{emptyText ?? t("common.empty")}</div>;
  return <>{children(q.data)}</>;
}

/** Inline error under a form/action. */
export function ActionError({ error }: { error: unknown }) {
  const { lang } = useMT();
  if (!error) return null;
  if (error instanceof ApiError) {
    const details = error.details as { errors?: Message[] };
    return (
      <div className="stack" role="alert">
        <MError error={error} />
        {details?.errors && details.errors.length > 0 && (
          <ul className="small" style={{ margin: 0 }}>
            {details.errors.map((e, i) => (
              <li key={`${e.code}-${i}`}>{lang === "kz" ? e.message_kz : e.message_ru}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }
  return <ErrorState error={error} />;
}

export function Messages({ items, title }: { items: Message[] | undefined | null; title?: string }) {
  const { lang } = useMT();
  if (!items || items.length === 0) return null;
  return (
    <div className="stack">
      {title && <h3 style={{ margin: 0 }}>{title}</h3>}
      <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {items.map((m, i) => (
          <li key={`${m.code}-${i}`} className={`alert alert-${m.severity === "fail" ? "danger" : m.severity === "warn" ? "warn" : "info"}`}>
            <span className="xs mono muted">{m.code}</span>
            <div>{lang === "kz" ? m.message_kz : m.message_ru}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const OUTCOME_TONE: Record<string, Tone> = {
  positive_signal: "ok", mixed: "warn", not_confirmed: "neutral", needs_more_data: "neutral",
  invalid_due_to_fidelity: "danger", invalid_due_to_comparability: "danger",
};
const FID_TONE: Record<string, Tone> = { high: "ok", moderate: "warn", low: "danger", unknown: "neutral" };
const PILOT_TONE: Record<string, Tone> = { draft: "neutral", ready: "info", active: "ok", completed: "info", stopped: "warn" };
const VSTATUS_TONE: Record<string, Tone> = { draft: "neutral", reviewed: "ok", archived: "warn" };

export function OutcomeBadge({ status }: { status: string | null | undefined }) {
  const { t2 } = useMT();
  if (!status) return <span className="muted">—</span>;
  return <Badge tone={OUTCOME_TONE[status] ?? "neutral"}>{t2(`outcome.${status}`)}</Badge>;
}

export function FidelityBadge({ code }: { code: string | null | undefined }) {
  const { t2 } = useMT();
  if (!code) return <span className="muted">—</span>;
  return <Badge tone={FID_TONE[code] ?? "neutral"}>{t2(`fidc.${code}`)}</Badge>;
}

export function PilotStatusBadge({ status }: { status: string }) {
  const { t2 } = useMT();
  return <Badge tone={PILOT_TONE[status] ?? "neutral"}>{t2(`pilot.status.${status}`)}</Badge>;
}

export function VersionStatusBadge({ status }: { status: string }) {
  const { t2 } = useMT();
  return <Badge tone={VSTATUS_TONE[status] ?? "neutral"}>{t2(`iv.vstatus.${status}`)}</Badge>;
}

export function LabelText({ label }: { label: Label | null | undefined }) {
  const { lang } = useMT();
  if (!label) return <span className="muted">—</span>;
  return <span title={label.code ?? undefined}>{lang === "kz" ? label.label_kz : label.label_ru}</span>;
}

export function Share({ v }: { v: number | null | undefined }) {
  const { lang } = useMT();
  return <span className="mono">{pct(v, lang)}</span>;
}

export function PP({ v }: { v: number | null | undefined }) {
  const { lang } = useMT();
  if (v === null || v === undefined) return <span className="muted">—</span>;
  return <span className={`mono ${v > 0 ? "diff-pos" : v < 0 ? "diff-neg" : ""}`}>{pp(v, lang)}</span>;
}

export function Num({ v, digits = 0 }: { v: number | null | undefined; digits?: number }) {
  const { lang } = useMT();
  return <span className="mono">{num(v, lang, digits)}</span>;
}

export function Stat({ value, reason, digits = 2 }: { value: number | null | undefined; reason?: string | null; digits?: number }) {
  const { lang, t2 } = useMT();
  if (value === null || value === undefined) {
    return <span className="muted small" title={reason ?? undefined}>{t2("common.not_available")}{reason ? ` (${reason})` : ""}</span>;
  }
  return <span className="mono">{num(value, lang, digits)}</span>;
}

export function CIRange({ low, high, reason, asPP = false }: { low: number | null | undefined; high: number | null | undefined; reason?: string | null; asPP?: boolean }) {
  const { lang, t2, t } = useMT();
  if (low === null || low === undefined || high === null || high === undefined) {
    return <span className="muted small">{t2("fu.ci_unavailable")}{reason ? ` (${reason})` : ""}</span>;
  }
  const f = (x: number) => (asPP ? pp(x, lang) : pct(x, lang));
  return <span className="small">{t("common.ci95")}: {f(low)} … {f(high)}</span>;
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv" style={{ display: "grid", gridTemplateColumns: "minmax(140px, max-content) 1fr", gap: "4px 16px", margin: 0 }}>
      {rows.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt className="muted small">{k}</dt>
          <dd style={{ margin: 0 }}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
