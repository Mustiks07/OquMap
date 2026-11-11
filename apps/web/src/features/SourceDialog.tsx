import { useEffect, useRef } from "react";
import { useSource } from "../api/hooks";
import { useI18n } from "../i18n/I18n";
import { Badge, Button, QueryView } from "../ui";

/** Opens a citation: document, version, hash, physical/printed page or anchor, the fragment and its neighbours. */
export function SourceDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useI18n();
  const q = useSource(id);
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal?.();
    return () => d?.close?.();
  }, []);
  return (
    <dialog ref={ref} onClose={onClose} aria-label={t("common.source")} style={{ maxWidth: 720, width: "92vw", border: "1px solid var(--color-border)", borderRadius: 12, padding: 20 }}>
      <QueryView q={q}>
        {(s) => (
          <div className="stack" data-testid="source-dialog">
            <div className="spread">
              <h2 style={{ margin: 0 }}>{String(s.edition?.title ?? s.document_filename)}</h2>
              <Button onClick={onClose}>{t("common.close")}</Button>
            </div>
            <div className="row small">
              {s.is_demo && <Badge tone="synthetic">demo</Badge>}
              <Badge>v{s.document_version}</Badge>
              {s.page_physical != null && <Badge tone="info">{t("materials.page_physical")} {s.page_physical}</Badge>}
              {s.page_printed && <Badge tone="info">{t("materials.page")} {s.page_printed}</Badge>}
              <Badge>{t("materials.anchor")} {s.anchor}</Badge>
            </div>
            {s.heading && <strong>{s.heading}</strong>}
            <div className="quote">{s.text}</div>
            {s.context.length > 0 && (
              <div className="stack xs muted">
                {s.context.map((c) => <div key={c.source_id as string}>… {String(c.text).slice(0, 220)}</div>)}
              </div>
            )}
            <p className="xs muted">{s.document_filename} · sha256 <code>{s.document_sha256.slice(0, 16)}…</code> · source_id <code>{s.source_id}</code></p>
            <p className="xs muted">{t("materials.injection_note")}</p>
          </div>
        )}
      </QueryView>
    </dialog>
  );
}
