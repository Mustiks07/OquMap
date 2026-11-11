/** Presentation primitives. No API or analytics logic here. */
import { useId, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { pct, pp } from "./format";

export function Button({ variant = "default", size, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "danger" | "ghost"; size?: "sm" }) {
  const cls = ["btn", variant !== "default" ? `btn-${variant}` : "", size ? `btn-${size}` : "", className].join(" ").trim();
  return <button type="button" className={cls} {...rest} />;
}

export function Card({ title, actions, children, className = "", id }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section className={`card ${className}`} id={id} aria-labelledby={title && id ? `${id}-title` : undefined}>
      {(title || actions) && (
        <div className="card-title">
          {typeof title === "string" ? <h2 id={id ? `${id}-title` : undefined} style={{ fontSize: "var(--text-lg)" }}>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral" | "synthetic";

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Alert({ tone = "info", title, children, role }: { tone?: "info" | "warn" | "danger" | "ok"; title?: ReactNode; children?: ReactNode; role?: string }) {
  return (
    <div className={`alert alert-${tone}`} role={role ?? (tone === "danger" ? "alert" : "status")}>
      {title && <strong>{title}</strong>}
      {children}
    </div>
  );
}

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <span>{label ?? t("common.loading")}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n();
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="state" role="alert">
      <strong style={{ color: "var(--color-danger)" }}>{t("common.error")}</strong>
      <span>{e ? e.message : String((error as Error)?.message ?? error)}</span>
      {e?.requestId && (
        <span className="xs">
          {t("common.request_id")}: <code>{e.requestId}</code> · {e.code}
        </span>
      )}
      {onRetry && (
        <Button onClick={onRetry} variant="primary">
          {t("common.retry")}
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ children }: { children?: ReactNode }) {
  const { t } = useI18n();
  return <div className="state">{children ?? t("common.empty")}</div>;
}

/** Renders loading / error(with retry) / empty / content for a react-query result. */
export function QueryView<T>({ q, empty, children }: { q: { isLoading: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown }; empty?: (d: T) => boolean; children: (d: T) => ReactNode }) {
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.data === undefined) return <EmptyState />;
  if (empty && empty(q.data)) return <EmptyState />;
  return <>{children(q.data)}</>;
}

export function Field({ label, children, hint }: { label: string; children: (id: string) => ReactNode; hint?: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {hint && <span className="xs muted">{hint}</span>}
    </div>
  );
}

export function Select({ id, value, onChange, options, ariaLabel }: { id?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; ariaLabel?: string }) {
  return (
    <select id={id} className="input" value={value} aria-label={ariaLabel} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Tabs({ tabs, active, onChange, label }: { tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void; label: string }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((tb) => (
        <button key={tb.id} role="tab" type="button" className="tab" aria-selected={active === tb.id} onClick={() => onChange(tb.id)}>
          {tb.label}
        </button>
      ))}
    </div>
  );
}

export function Metric({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
      {sub && <span className="metric-sub">{sub}</span>}
    </div>
  );
}

export function ShareBar({ value, label }: { value: number | null | undefined; label?: string }) {
  const { lang } = useI18n();
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return (
    <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
      <div className="bar-track" style={{ flex: 1 }} role="img" aria-label={`${label ?? ""} ${pct(value, lang)}`}>
        <div className="bar-fill" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
      </div>
      <span className="mono small">{pct(value, lang)}</span>
    </div>
  );
}

export function Diff({ value }: { value: number | null | undefined }) {
  const { lang } = useI18n();
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return <span className={value > 0 ? "diff-pos" : value < 0 ? "diff-neg" : ""}>{pp(value, lang)}</span>;
}

const STATUS_TONE: Record<string, Tone> = {
  difficult: "danger",
  attention: "warn",
  stable: "ok",
  not_measured: "neutral",
  unverified_mapping: "warn",
  insufficient_data: "neutral",
  measured: "ok",
  no_data: "neutral",
  comparable: "ok",
  limited: "warn",
  not_comparable: "danger",
  positive_signal: "ok",
  not_confirmed: "neutral",
  needs_more_data: "neutral",
  needs_revision: "danger",
  optimal: "ok",
  feasible: "info",
  infeasible: "danger",
  unknown: "warn",
  invalid: "danger",
  draft: "neutral",
  approved: "ok",
  superseded: "neutral",
  proposed: "warn",
  confirmed: "ok",
  rejected: "neutral",
};

export function StatusBadge({ status, labelKey }: { status: string | null | undefined; labelKey?: DictKey }) {
  const { t } = useI18n();
  if (!status) return null;
  const key = (labelKey ?? `status.${status}`) as DictKey;
  const label = t(key);
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{label === key ? status : label}</Badge>;
}

export function SyntheticBadge() {
  const { t } = useI18n();
  return (
    <Badge tone="synthetic" title={t("synthetic.note")}>
      ◆ {t("synthetic.badge")}
    </Badge>
  );
}

export function ModeBadge({ mode, fallback }: { mode: string; fallback?: string | null }) {
  const { t } = useI18n();
  const tone: Tone = mode === "live_model" ? "info" : mode === "recorded_demo" ? "synthetic" : "neutral";
  return (
    <span className="row" style={{ gap: 6 }}>
      <Badge tone={tone}>{t(`ai.mode.${mode}` as DictKey)}</Badge>
      {fallback && (
        <span className="xs muted">
          {t("ai.fallback")}: <code>{fallback}</code>
        </span>
      )}
    </span>
  );
}

export function ReasonList({ reasons }: { reasons: { code: string; severity: string; message_ru: string; message_kz: string }[] }) {
  const { lang } = useI18n();
  if (!reasons.length) return null;
  return (
    <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {reasons.map((r, i) => (
        <li key={`${r.code}-${i}`} className={`alert alert-${r.severity === "fail" ? "danger" : r.severity === "warn" ? "warn" : "info"}`}>
          <span className="xs mono muted">{r.code}</span>
          <div>{lang === "kz" ? r.message_kz : r.message_ru}</div>
        </li>
      ))}
    </ul>
  );
}

export function StaleBanner({ ctx, onRecompute }: { ctx?: { is_stale: boolean; dataset_version: number; current_dataset_version: number } | null; onRecompute?: () => void }) {
  const { t } = useI18n();
  if (!ctx?.is_stale) return null;
  return (
    <Alert tone="warn" title={t("stale.title")} role="alert">
      <div className="spread">
        <span>{t("stale.body", { from: ctx.dataset_version, to: ctx.current_dataset_version })}</span>
        {onRecompute && (
          <Button size="sm" variant="primary" onClick={onRecompute}>
            {t("stale.recompute")}
          </Button>
        )}
      </div>
    </Alert>
  );
}

export function Disclosure({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button type="button" className="btn btn-ghost btn-sm" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} {summary}
      </button>
      {open && <div style={{ marginTop: 8 }}>{children}</div>}
    </div>
  );
}

export function CI({ low, high, reason }: { low?: number | null; high?: number | null; reason?: string | null }) {
  const { t, lang } = useI18n();
  if (low === null || low === undefined || high === null || high === undefined) {
    return (
      <span className="muted small" title={reason ?? undefined}>
        {t("common.ci_unavailable")}
        {reason ? ` (${reason})` : ""}
      </span>
    );
  }
  return (
    <span className="small">
      {t("common.ci95")}: {pct(low, lang)} – {pct(high, lang)}
    </span>
  );
}
