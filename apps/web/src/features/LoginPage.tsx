import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, setToken } from "../api/client";
import type { LoginResponse } from "../api/types";
import { useI18n } from "../i18n/I18n";
import { useAppState } from "../state/AppState";
import { Alert, Button, Card, ErrorState, SyntheticBadge } from "../ui";

export function LoginPage() {
  const { t, lang, setLang } = useI18n();
  const { setUser, setDatasetId } = useAppState();
  const [persona, setPersona] = useState("methodist");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const qc = useQueryClient();

  async function enter() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<LoginResponse>("/api/v1/auth/demo-login", { persona });
      setToken(r.token);
      setUser(r.user);
      qc.clear();
      if (persona === "other_org") setDatasetId(null);
      nav("/datasets");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page" style={{ maxWidth: 760, paddingTop: 64 }}>
      <div className="spread" style={{ marginBottom: 16 }}>
        <span className="brand" style={{ fontSize: "var(--text-2xl)" }}>OquMap</span>
        <div className="row" role="group" aria-label={t("header.lang")} style={{ gap: 4 }}>
          {(["ru", "kz"] as const).map((l) => (
            <Button key={l} size="sm" variant={lang === l ? "primary" : "default"} aria-pressed={lang === l} onClick={() => setLang(l)}>
              {l.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>
      <Card>
        <h1>{t("login.title")}</h1>
        <p className="muted">{t("app.tagline")}</p>
        <p>{t("login.lead")}</p>
        <div className="row" style={{ marginBottom: 16 }}>
          <SyntheticBadge />
        </div>
        <fieldset style={{ border: "none", padding: 0, margin: "0 0 16px" }}>
          <legend className="small" style={{ fontWeight: 600, marginBottom: 8 }}>{t("login.persona")}</legend>
          <div className="stack">
            {(["methodist", "viewer", "other_org"] as const).map((p) => (
              <label key={p} className="checkbox">
                <input type="radio" name="persona" value={p} checked={persona === p} onChange={() => setPersona(p)} />
                {t(`login.${p}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <Button variant="primary" onClick={enter} disabled={busy} data-testid="enter-demo">
          {t("login.enter")}
        </Button>
        <div style={{ marginTop: 16 }}>
          <Alert tone="warn">{t("login.demo_only")}</Alert>
        </div>
        {error ? <ErrorState error={error} onRetry={enter} /> : null}
      </Card>
    </main>
  );
}
