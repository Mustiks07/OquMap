import { useState } from "react";
import { api } from "../api/client";
import { useCurrentDataset, useCurriculum } from "../api/hooks";
import type { AssistantAnswer } from "../api/types";
import { useI18n } from "../i18n/I18n";
import { useAppState } from "../state/AppState";
import { Button, Disclosure, ErrorState, Loading, ModeBadge } from "../ui";
import { AiStatusCard } from "./AiStatusCard";

interface Msg {
  role: "user" | "bot";
  text: string;
  answer?: AssistantAnswer;
}

/** Context assistant: receives the current dataset, topic, editions and filters with every question. */
export function Assistant({ onClose }: { onClose: () => void }) {
  const { t, lang, pick } = useI18n();
  const st = useAppState();
  const { dataset } = useCurrentDataset();
  const cur = useCurriculum();
  const topic = cur.data?.topics.find((x) => x.id === st.topicId);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function ask(q: string) {
    if (!q.trim() || !st.datasetId) return;
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setText("");
    setBusy(true);
    setError(null);
    try {
      const a = await api.post<AssistantAnswer>("/api/v1/assistant/query", {
        question: q, lang,
        context: { dataset_id: st.datasetId, filters: st.filters, topic_id: st.topicId, edition_a_id: st.editionA, edition_b_id: st.editionB },
      });
      setMsgs((m) => [...m, { role: "bot", text: String(a.output.text ?? ""), answer: a }]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="assistant" aria-label={t("assistant.title")} data-testid="assistant">
      <div className="spread" style={{ padding: 12, borderBottom: "1px solid var(--color-border)" }}>
        <strong>{t("assistant.title")}</strong>
        <Button size="sm" onClick={onClose}>{t("common.close")}</Button>
      </div>
      <p className="xs muted" style={{ padding: "8px 12px", margin: 0 }}>
        {t("assistant.context", { dataset: dataset ? (lang === "kz" ? dataset.name_kz : dataset.name_ru) : "—", topic: topic ? `${topic.code} ${pick(topic, "title")}` : "—" })}
      </p>
      <div style={{ padding: "0 12px 8px" }}><AiStatusCard /></div>
      <div className="stack" style={{ flex: 1, overflowY: "auto", padding: 12 }} aria-live="polite">
        {msgs.length === 0 && (
          <div className="stack">
            <span className="small muted">{t("assistant.empty")}</span>
            {(["assistant.suggest1", "assistant.suggest2", "assistant.suggest3", "assistant.suggest4"] as const).map((k) => (
              <Button key={k} size="sm" onClick={() => ask(t(k))} style={{ justifyContent: "flex-start", whiteSpace: "normal", textAlign: "left" }}>{t(k)}</Button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role === "user" ? "chat-user" : "chat-bot"}`}>
            {m.answer && <div style={{ marginBottom: 6 }}><ModeBadge mode={m.answer.mode} fallback={m.answer.fallback_reason} /></div>}
            {m.text}
            {m.answer && (
              <Disclosure summary={t("assistant.tools")}>
                <ul className="xs">{m.answer.tool_calls.map((c, j) => <li key={j}><code>{String(c.tool)}</code> {JSON.stringify(c.input)}</li>)}</ul>
                {m.answer.sources.length > 0 && (
                  <>
                    <strong className="xs">{t("assistant.sources")}</strong>
                    <ul className="xs">{m.answer.sources.map((s) => <li key={String(s.source_id)}>{String(s.document)} · {s.page_printed ? `с. ${String(s.page_printed)}` : String(s.anchor)}</li>)}</ul>
                  </>
                )}
                <span className="xs muted">analysis: {m.answer.analysis_ids.map((x) => x.slice(0, 8)).join(", ")}</span>
              </Disclosure>
            )}
          </div>
        ))}
        {busy && <Loading />}
        {error ? <ErrorState error={error} /> : null}
      </div>
      <form className="row" style={{ padding: 12, borderTop: "1px solid var(--color-border)", flexWrap: "nowrap" }} onSubmit={(e) => { e.preventDefault(); ask(text); }}>
        <label className="sr-only" htmlFor="assistant-q">{t("assistant.title")}</label>
        <input id="assistant-q" className="input" value={text} placeholder={t("assistant.placeholder")} onChange={(e) => setText(e.target.value)} maxLength={2000} />
        <Button type="submit" variant="primary" disabled={busy || !text.trim()}>{t("assistant.send")}</Button>
      </form>
    </aside>
  );
}
