import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useI18n } from "../i18n/I18n";
import { useAppState } from "../state/AppState";
import { Alert, Badge, Button, Card, ErrorState, Field, QueryView } from "../ui";
import { dateTime } from "../ui/format";

interface UserRow { id: string; username: string; display_name: string; roles: string[]; is_active: boolean; last_login_at: string | null }
const ROLES = ["admin", "methodist", "approver", "teacher", "viewer"];

export function UsersPage() {
  const { t, lang } = useI18n();
  const { user } = useAppState();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["users"], queryFn: () => api.get<UserRow[]>("/api/v1/admin/users"), enabled: !user?.org_is_demo });
  const [form, setForm] = useState({ username: "", display_name: "", password: "", roles: ["methodist"] as string[] });
  const [error, setError] = useState<unknown>(null);
  if (user?.org_is_demo) return <div className="page"><Alert tone="info">{t("users.demo")}</Alert></div>;

  async function create() {
    setError(null);
    try {
      await api.post("/api/v1/admin/users", form);
      setForm({ username: "", display_name: "", password: "", roles: ["methodist"] });
      await qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      setError(e);
    }
  }
  async function toggle(u: UserRow) {
    setError(null);
    try {
      await api.post(`/api/v1/admin/users/${u.id}`, { is_active: !u.is_active });
      await qc.invalidateQueries({ queryKey: ["users"] });
    } catch (e) {
      setError(e);
    }
  }
  return (
    <div className="page stack">
      <div className="page-header"><h1>{t("users.title")}</h1></div>
      {error ? <ErrorState error={error} /> : null}
      <Card title={t("users.create")}>
        <div className="filters">
          <Field label={t("users.username")}>{(id) => <input id={id} className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />}</Field>
          <Field label={t("users.display_name")}>{(id) => <input id={id} className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />}</Field>
          <Field label={t("users.password")}>{(id) => <input id={id} type="password" className="input" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />}</Field>
          <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
            <legend className="xs muted">{t("users.roles")}</legend>
            {ROLES.map((r) => (
              <label key={r} className="checkbox" style={{ marginRight: 8 }}>
                <input type="checkbox" checked={form.roles.includes(r)} onChange={(e) => setForm({ ...form, roles: e.target.checked ? [...form.roles, r] : form.roles.filter((x) => x !== r) })} /> {r}
              </label>
            ))}
          </fieldset>
          <Button variant="primary" onClick={create} disabled={!form.username || !form.password || !form.roles.length}>{t("users.create")}</Button>
        </div>
      </Card>
      <Card title={t("users.title")}>
        <QueryView q={q}>
          {(rows) => (
            <div className="table-wrap" tabIndex={0}>
              <table className="table">
                <thead><tr><th>{t("users.username")}</th><th>{t("users.display_name")}</th><th>{t("users.roles")}</th><th>{t("users.active")}</th><th /></tr></thead>
                <tbody>
                  {rows.map((u) => (
                    <tr key={u.id}>
                      <td className="mono">{u.username}</td><td>{u.display_name}</td>
                      <td>{u.roles.map((r) => <Badge key={r}>{r}</Badge>)}</td>
                      <td>{u.is_active ? <Badge tone="ok">{t("common.yes")}</Badge> : <Badge>{t("common.no")}</Badge>}<div className="xs muted">{dateTime(u.last_login_at, lang)}</div></td>
                      <td>{u.id !== user?.id && <Button size="sm" onClick={() => toggle(u)}>{u.is_active ? t("users.deactivate") : t("users.activate")}</Button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryView>
      </Card>
    </div>
  );
}
