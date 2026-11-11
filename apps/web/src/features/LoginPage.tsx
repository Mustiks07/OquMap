import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, setToken } from "../api/client";
import { useConfig } from "../api/hooks";
import type { LoginResponse } from "../api/types";
import { useI18n } from "../i18n/I18n";
import { useAppState } from "../state/AppState";
import { Alert, Button, Card, Disclosure, ErrorState, Field, Loading, SyntheticBadge } from "../ui";

export function LoginPage() {
  const { t, lang, setLang } = useI18n();
  const st = useAppState();
  const cfg = useConfig();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [busy, setBusy] = useState<"" | "demo" | "account" | "qa">("");
  const [error, setError] = useState<unknown>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [persona, setPersona] = useState("methodist");

  async function finish(r: LoginResponse, recommended?: string | null) {
    setToken(r.token);
    st.setUser(r.user);
    qc.clear();
    st.resetProgress();
    if (recommended) {
      st.setDatasetId(recommended);
      nav("/overview");
    } else {
      st.setDatasetId(null);
      nav("/datasets");
    }
  }

  async function openDemo(p?: string) {
    setBusy(p ? "qa" : "demo");
    setError(null);
    try {
      const r = await api.post<LoginResponse>("/api/v1/auth/demo-login", p ? { persona: p } : {});
      await finish(r, r.recommended_dataset_id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy("account");
    setError(null);
    try {
      await finish(await api.post<LoginResponse>("/api/v1/auth/login", { username, password }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy("");
    }
  }

  const c = cfg.data;
  return (
    <main className="page" style={{ maxWidth: 760, paddingTop: 56 }}>
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
        {cfg.isLoading ? <Loading /> : c?.demo_login_enabled ? (
          <div className="stack" style={{ marginBottom: 8 }}>
            <div className="row"><SyntheticBadge /></div>
            <Button variant="primary" onClick={() => openDemo()} disabled={busy !== ""} data-testid="enter-demo"
              style={{ minHeight: 52, fontSize: "var(--text-lg)", alignSelf: "flex-start" }}>
              {t("login.open_demo")}
            </Button>
            {busy === "demo" && <Loading label={t("login.preparing")} />}
            {c.deployment_mode === "public_demo" && <p className="small muted">{t("login.open_demo_note")}</p>}
            <Alert tone="warn">{t("login.demo_only")}</Alert>
          </div>
        ) : (
          <Alert tone="info">{t("login.demo_disabled")}</Alert>
        )}
        {error ? <ErrorState error={error} /> : null}
      </Card>
      <div style={{ marginTop: 16 }}>
        <Card title={t("login.account")}>
          <form className="stack" onSubmit={signIn} style={{ maxWidth: 360 }}>
            <Field label={t("login.username")}>{(id) => <input id={id} className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />}</Field>
            <Field label={t("login.password")}>{(id) => <input id={id} className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
            <Button type="submit" disabled={!username || !password || busy !== ""} data-testid="sign-in">{t("login.sign_in")}</Button>
          </form>
        </Card>
      </div>
      {c?.qa_personas_enabled && (
        <div style={{ marginTop: 16 }}>
          <Disclosure summary={t("login.qa")}>
            <div className="stack">
              {(["methodist", "viewer", "other_org"] as const).map((p) => (
                <label key={p} className="checkbox">
                  <input type="radio" name="persona" value={p} checked={persona === p} onChange={() => setPersona(p)} />
                  {t(`login.${p}`)}
                </label>
              ))}
              <Button onClick={() => openDemo(persona)} disabled={busy !== ""} data-testid="enter-qa">{t("login.enter")}</Button>
            </div>
          </Disclosure>
        </div>
      )}
    </main>
  );
}
