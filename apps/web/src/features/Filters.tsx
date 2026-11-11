import { useCurriculum } from "../api/hooks";
import type { Filters } from "../api/types";
import { useI18n } from "../i18n/I18n";
import type { DictKey } from "../i18n/dict";
import { useAppState } from "../state/AppState";
import { Card, Field, Select } from "../ui";

/** Shared filter bar; the same filters drive every analysis, the assistant and the report. */
export function FilterBar({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  const { filters, setFilters } = useAppState();
  const cur = useCurriculum();
  const set = (patch: Partial<Filters>) => setFilters({ ...filters, ...patch });
  const opt = (prefix: string, values: string[]) => values.map((v) => ({ value: v, label: t(`${prefix}.${v}` as DictKey) }));
  return (
    <Card className="filters-card">
      <div className="filters" data-testid="filters">
        <Field label={t("filters.schools")}>
          {(id) => (
            <Select id={id} value={filters.school_ids?.[0] ?? ""} onChange={(v) => set({ school_ids: v ? [v] : [] })}
              options={[{ value: "", label: t("filters.all") }, ...(cur.data?.schools ?? []).map((s) => ({ value: s.id, label: s.code }))]} />
          )}
        </Field>
        <Field label={t("filters.editions")}>
          {(id) => (
            <Select id={id} value={filters.edition_ids?.[0] ?? ""} onChange={(v) => set({ edition_ids: v ? [v] : [] })}
              options={[{ value: "", label: t("filters.all") }, ...(cur.data?.editions ?? []).map((e) => ({ value: e.id, label: `${e.code} — ${e.title}` }))]} />
          )}
        </Field>
        <Field label={t("filters.attempt")}>
          {(id) => <Select id={id} value={filters.attempt_rule ?? "first"} onChange={(v) => set({ attempt_rule: v })} options={opt("filters.attempt", ["first", "last"])} />}
        </Field>
        <Field label={t("filters.omitted")}>
          {(id) => <Select id={id} value={filters.omitted_policy ?? "as_incorrect"} onChange={(v) => set({ omitted_policy: v })} options={opt("filters.omitted", ["as_incorrect", "exclude"])} />}
        </Field>
        <Field label={t("filters.aggregation")}>
          {(id) => <Select id={id} value={filters.aggregation ?? "learner"} onChange={(v) => set({ aggregation: v })} options={opt("filters.aggregation", ["learner", "class"])} />}
        </Field>
        <Field label={t("filters.mapping")}>
          {(id) => (
            <Select id={id} value={filters.mapping_status ?? "confirmed_only"} onChange={(v) => set({ mapping_status: v })}
              options={opt("filters.mapping", ["confirmed_only", "include_proposed"])} />
          )}
        </Field>
      </div>
      {!compact && <p className="xs muted" style={{ margin: "8px 0 0" }}>{t("filters.applied")}</p>}
    </Card>
  );
}
