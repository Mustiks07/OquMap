import { useEffect } from "react";
import { useCouncil, type CouncilOutput } from "../api/wow";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Disclosure, ErrorState, Loading, ModeBadge, type Tone } from "../ui";

const VERDICT_TONE: Record<string, Tone> = { accepted: "ok", weakened: "warn", blocked: "danger" };

/** "Провести консилиум по теме": public audit trail, critic verdicts and a server-verified final card. */
export function CouncilPanel({ topicId, autoRun = false }: { topicId: string; autoRun?: boolean }) {
  const { t, lang } = useI18n();
  const { datasetId } = useAppState();
  const m = useCouncil();
  const out = m.data?.output as CouncilOutput | undefined;
  const run = () => datasetId && m.mutate({ dataset_id: datasetId, topic_id: topicId, lang });
  useEffect(() => {
    if (autoRun && datasetId) m.mutate({ dataset_id: datasetId, topic_id: topicId, lang });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, datasetId, topicId, lang]);
  return (
    <div className="stack" data-testid="council">
      {!autoRun && (
        <div className="row">
          <Button variant="primary" onClick={run} disabled={m.isPending} data-testid="run-council">{t("council.run")}</Button>
          <span className="xs muted">{t("council.hint")}</span>
        </div>
      )}
      {m.isPending && <Loading label={t("council.running")} />}
      {m.isError && <ErrorState error={m.error} onRetry={run} />}
      {out && m.data && (
        <>
          <div className="row" style={{ gap: 8 }}>
            <ModeBadge mode={m.data.mode} fallback={m.data.fallback_reason} />
            <span className="xs muted">{t("council.critic_rules")} · {t("header.version")} v{out.dataset_version}</span>
          </div>
          {out.highlight && (
            <Alert tone={out.highlight.verdict === "blocked" ? "danger" : "warn"} title={t(`council.highlight.${out.highlight.verdict}` as DictKey)}>
              <div data-testid="council-highlight">
                <q>{out.claims.find((c) => c.id === out.highlight!.claim_id)?.text}</q>
                <div className="small">{t("council.critic")}: {out.highlight.reasons_ru.join("; ")}</div>
              </div>
            </Alert>
          )}
          <section className="final-card" data-testid="council-final" aria-label={t("council.final")}>
            <h3>{t("council.final")}</h3>
            <dl>
              <dt>{t("council.claim")}</dt><dd>{out.final.claim}</dd>
              <dt>{t("council.action")}</dt><dd>{out.final.recommended_action}</dd>
              <dt>{t("council.verification")}</dt><dd>{out.final.verification_plan}</dd>
              <dt>{t("council.limitations")}</dt><dd><ul className="small">{out.final.limitations.map((l) => <li key={l}>{l}</li>)}</ul></dd>
              <dt>{t("council.evidence")}</dt><dd className="xs mono">{out.final.evidence_ids.length} · {out.final.evidence_ids.slice(0, 6).map((e) => e.split(":").slice(0, 2).join(":").slice(0, 28)).join(", ")}…</dd>
            </dl>
          </section>
          <h4>{t("council.claims")}</h4>
          <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }} data-testid="council-claims">
            {out.claims.map((c) => {
              const v = out.verdicts.find((x) => x.claim_id === c.id);
              return (
                <li key={c.id} className={`claim claim-${v?.verdict ?? "accepted"}`}>
                  <div className="row" style={{ gap: 6 }}>
                    <span className="xs mono">{c.id}</span>
                    <Badge tone="info">{out.roles[c.role]}</Badge>
                    {v && <Badge tone={VERDICT_TONE[v.verdict]}>{t(`council.verdict.${v.verdict}` as DictKey)}</Badge>}
                  </div>
                  <div className={v?.verdict === "blocked" ? "struck" : ""}>{c.text}</div>
                  {v && v.reasons_ru.length > 0 && <div className="xs muted">{t("council.critic")}: {v.reasons_ru.join("; ")}</div>}
                </li>
              );
            })}
          </ul>
          {out.agreements.length > 0 && <p className="small">✓ {out.agreements.map((a) => a.text_ru).join(" ")}</p>}
          <Disclosure summary={`${t("council.trail")} (${out.steps.length})`}>
            <ol className="xs stack" data-testid="council-trail">
              {out.steps.map((s) => (
                <li key={s.n}>
                  <strong>{s.role_label}</strong> · {t(`council.action.${s.action}` as DictKey)}
                  {s.tool && <> · <code>{s.tool}</code>{s.input ? <> <span className="mono">{JSON.stringify(s.input).slice(0, 120)}</span></> : null}</>}
                  {s.blocked && <Badge tone="warn">{s.blocked}</Badge>}
                  {s.output_ref && <div className="muted mono">→ {Object.entries(s.output_ref).map(([k, v]) => `${k}=${String(v).slice(0, 12)}`).join(" ")}</div>}
                  {s.facts && s.facts.length > 0 && <div className="muted">{t("council.facts")}: {s.facts.length}</div>}
                  {s.claim && <div>«{s.claim.text}»</div>}
                  {s.verdict && <div><Badge tone={VERDICT_TONE[s.verdict]}>{t(`council.verdict.${s.verdict}` as DictKey)}</Badge> {s.claim_id} {s.reasons_ru?.join("; ")}</div>}
                  {s.note_ru && <div className="muted">{s.note_ru}</div>}
                </li>
              ))}
            </ol>
            <p className="xs muted">{out.note_ru}</p>
          </Disclosure>
        </>
      )}
    </div>
  );
}
