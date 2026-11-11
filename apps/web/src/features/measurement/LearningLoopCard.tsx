/** Learning-loop block of a decision created from a pilot conclusion (decision.snapshot.learning_loop). Read-only:
 *  the approval process of the decision page is unchanged. */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, Card } from "../../ui";
import { CIRange, CodeLabel, FidelityBadge, KV, Messages, OutcomeBadge, PP } from "./components";
import type { Message } from "./api";
import { useMT } from "./i18n";

const ACKS = new Set(["no_effectiveness_conclusion", "requires_new_pilot_or_implementation", "synthetic_data_only", "observational_design", "interim_result"]);

export interface LearningLoopSnapshot {
  pilot_id: string; pilot_code: string; outcome_id: string; outcome_status: string; causal_level: string; fidelity_class: string;
  conclusion_id: string; decision: string; summary_ru: string; evidence_ids: string[]; intervention_id: string;
  intervention_code?: string; intervention_version?: number; intervention_title_ru?: string; design?: string; outcome_as_of?: string | null;
  primary?: { estimand: string; estimate: number | null; ci_low: number | null; ci_high: number | null; ci_unavailable_reason: string | null } | null;
  decision_basis?: string; acknowledged_limitation_codes?: string[]; lessons_ru?: string; open_questions?: string[];
  limitations?: Message[]; is_synthetic?: boolean;
}

export function LearningLoopCard({ loop }: { loop: LearningLoopSnapshot | undefined | null }) {
  const { t2 } = useMT();
  if (!loop) return null;
  const p = loop.primary;
  return (
    <Card title={t2("loop.title")} id="learning-loop">
      <div className="stack" data-testid="learning-loop">
        <KV rows={[
          [t2("loop.pilot"), <Link key="p" to={`/pilots/${loop.pilot_id}`} className="mono">{loop.pilot_code}</Link>],
          [t2("loop.intervention"), <Link key="i" to={`/interventions/${loop.intervention_id}`}>
            {loop.intervention_code ?? ""}{loop.intervention_version ? ` · v${loop.intervention_version}` : ""}{loop.intervention_title_ru ? ` — ${loop.intervention_title_ru}` : ""}</Link>],
          [t2("loop.outcome"), <span key="o"><OutcomeBadge status={loop.outcome_status} /> {loop.outcome_as_of ? t2("common.as_of", { date: loop.outcome_as_of }) : ""}</span>],
          [t2("fu.fidelity"), <FidelityBadge key="f" code={loop.fidelity_class} />],
          [t2("fu.causal"), <CodeLabel key="c" prefix="causal." code={loop.causal_level} />],
          ...(p ? [[t2(`fu.estimand.${p.estimand}`), <span key="e"><PP v={p.estimate} /> · <CIRange low={p.ci_low} high={p.ci_high} reason={p.ci_unavailable_reason} asPP /></span>] as [string, ReactNode]] : []),
          [t2("fu.decision"), <span key="d">{t2(`fu.decision.${loop.decision}`)}{loop.decision_basis ? ` · ${t2(`fu.basis.${loop.decision_basis}`)}` : ""}</span>],
          [t2("loop.conclusion"), loop.summary_ru],
          ...(loop.lessons_ru ? [[t2("fu.lessons"), loop.lessons_ru] as [string, string]] : []),
          [t2("loop.evidence"), <span key="ev" className="xs mono">{loop.evidence_ids.map((e) => e.slice(0, 8)).join(", ") || "—"}</span>],
        ]} />
        {loop.is_synthetic && <p className="small" style={{ margin: 0 }}><Badge tone="synthetic">{t2("common.synthetic_demo")}</Badge></p>}
        {(loop.acknowledged_limitation_codes ?? []).length > 0 && (
          <ul className="small" style={{ margin: 0 }}>
            {(loop.acknowledged_limitation_codes ?? []).map((c) => <li key={c}><CodeLabel prefix={ACKS.has(c) ? "ack." : "rule."} code={c} /></li>)}
          </ul>
        )}
        {(loop.open_questions ?? []).length > 0 && <ul className="small" style={{ margin: 0 }}>{(loop.open_questions ?? []).map((q, i) => <li key={i}>{q}</li>)}</ul>}
        <Messages items={loop.limitations ?? []} title={t2("loop.limitations")} />
        <p style={{ margin: 0 }}><Link to={`/pilots/${loop.pilot_id}/follow-up`}>{t2("loop.open")}</Link></p>
      </div>
    </Card>
  );
}
