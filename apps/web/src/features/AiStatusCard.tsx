import { useAiStatus } from "../api/hooks";
import { useI18n } from "../i18n/I18n";
import { dictionaries, type DictKey } from "../i18n/dict";
import { Badge, Disclosure, ModeBadge } from "../ui";

/** What AI the user actually gets: provider, model ID, live / recorded / template mode, capabilities, data policy. */
export function AiStatusCard({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  const q = useAiStatus();
  const s = q.data;
  if (!s) return null;
  const reason = s.live_blocked_reason ?? null;
  const reasonText = reason && `aistatus.reason.${reason}` in dictionaries.ru ? t(`aistatus.reason.${reason}` as DictKey) : reason;
  const c = s.capabilities;
  return (
    <div className="stack" style={{ gap: 4 }} data-testid="ai-status">
      <span className="row xs" style={{ gap: 6 }}>
        <strong>{t("aistatus.title")}:</strong>
        <ModeBadge mode={s.mode} />
        <span className="muted mono">{s.provider === "none" ? t("aistatus.none") : `${s.provider}${s.model ? ` · ${s.model}` : ""}`}</span>
      </span>
      {(reasonText || s.config_error) && (
        <span className="xs muted">{s.config_error ? `${t("aistatus.config_error")}: ${s.config_error}` : `${t("aistatus.blocked")}: ${reasonText}`}</span>
      )}
      {s.data_policy === "may_train" && (
        <div className="alert alert-warn xs" role="note" data-testid="ai-policy-warning">{s.data_policy_note_ru}</div>
      )}
      {!compact && (
        <Disclosure summary={t("aistatus.caps")}>
          <dl className="xs" style={{ margin: 0 }}>
            <dt>{t("aistatus.provider")}</dt><dd className="mono">{s.provider}</dd>
            <dt>{t("aistatus.model")}</dt><dd className="mono">{s.model ?? "—"}</dd>
            {s.provider !== "none" && (
              <>
                <dt>{t("aistatus.caps")}</dt>
                <dd>
                  {c.structured_output && <Badge tone="info">{t("aistatus.structured")}</Badge>}{" "}
                  {c.tool_calling && <Badge tone="info">{t("aistatus.tools")}</Badge>}{" "}
                  {c.max_context_tokens ? <span>{t("aistatus.context")}: {c.max_context_tokens}</span> : null}
                  <div className="muted">{c.probed ? t("aistatus.probed") : t("aistatus.declared")}</div>
                </dd>
                <dt>{t("aistatus.policy")}</dt>
                <dd><code>{s.data_policy}</code>{s.data_policy_note_ru && s.data_policy !== "may_train" ? ` — ${s.data_policy_note_ru}` : ""}</dd>
              </>
            )}
            {!s.real_data_allowed && (<><dt /><dd>{t("aistatus.real_data_off")}</dd></>)}
            {s.fallback_chain.length > 0 && (<><dt>{t("aistatus.fallback")}</dt><dd className="mono">{s.fallback_chain.join(" → ")}</dd></>)}
          </dl>
        </Disclosure>
      )}
    </div>
  );
}
