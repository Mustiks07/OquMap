/** Measurement & learning-loop screens: RU/KZ dictionary, rendering from API payloads, empty/error/forbidden states and
 *  real actions (requests sent with the right method and body). fetch is mocked per URL. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { I18nProvider, useI18n } from "../i18n/I18n";
import { AppStateProvider, useAppState } from "../state/AppState";
import { useEffect } from "react";
import { mdict } from "../features/measurement/i18n";
import { QualityDetailPage, QualityListPage } from "../features/quality/QualityPages";
import { PortfolioPage } from "../features/followup/PortfolioPage";
import { FollowUpPage } from "../features/followup/FollowUpPage";
import { PilotDetailPage } from "../features/interventions/PilotPages";
import { InterventionsPage } from "../features/interventions/InterventionPages";

type Handler = (init: RequestInit | undefined, url: string) => { status?: number; body: unknown };
let routes: [RegExp, Handler][] = [];
const calls: { url: string; method: string; body: unknown }[] = [];

function mockFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const hit = routes.find(([re]) => re.test(`${method} ${url}`));
    const res = hit ? hit[1](init, url) : { status: 404, body: { error: { code: "not_found", message: "not found", details: {} }, request_id: "t" } };
    return new Response(JSON.stringify(res.body), { status: res.status ?? 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
}

const USER = { id: "u", username: "m", display_name: "Методист", roles: ["methodist", "approver"], org_id: "o", org_name: "Org", org_is_demo: true };

function SetUser({ roles }: { roles: string[] }) {
  const { setUser } = useAppState();
  useEffect(() => setUser({ ...USER, roles }), [roles, setUser]);
  return null;
}

function LangButton() {
  const { setLang } = useI18n();
  return <button onClick={() => setLang("kz")}>to-kz</button>;
}

function renderAt(path: string, route: string, el: React.ReactNode, roles = ["methodist", "approver"]) {
  localStorage.clear();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <I18nProvider initial="ru">
        <AppStateProvider>
          <SetUser roles={roles} />
          <LangButton />
          <MemoryRouter initialEntries={[path]}>
            <Routes><Route path={route} element={el} /></Routes>
          </MemoryRouter>
        </AppStateProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const msg = (code: string, severity = "warn") => ({ code, severity, params: {}, message_ru: `RU ${code}`, message_kz: `KZ ${code}` });
const stat = (value: number | null, reason: string | null = null) => ({ value, unavailable_reason: reason });
const ASSESSMENT = { assessment_id: "a1", code: "DIAG-BASE", stage: "followup", administered_on: "2026-09-14", form_id: "f", form_code: "F-T3-DIAG",
  form_name: "Диагностика", scale_code: "S-T3-DIAG", linking_method: "identical_form", dataset_id: "d" };
const ITEM = {
  item_id: "i5", code: "Q05", max_points: 1, stem_ru: "Вычислите: 3/5 − 1/5.", stem_kz: "Есептеңіз: 3/5 − 1/5.",
  denominators: { present: 595, answered: 577, omitted: 18, missing: 0 }, p_value: 0.12, p_value_among_answered: 0.13, omission_rate: 0.03,
  missing_rate: 0, item_rest_correlation: stat(-0.23), upper_lower: { value: -0.2, unavailable_reason: null, group_size: 160, p_upper: 0.02, p_lower: 0.22 },
  options: [{ key: "A", text: "2/5", is_key: false, misconception: null, count: 367, share_of_answered: 0.64, mean_rest_score: 0.5, point_biserial_rest: stat(0.34) },
    { key: "C", text: "2/10", is_key: true, misconception: null, count: 73, share_of_answered: 0.13, mean_rest_score: 0.32, point_biserial_rest: stat(-0.23) }],
  invalid_response_values: 0, flags: [msg("negative_discrimination")], objectives: [{ objective_id: "o", code: "DEMO-M6-3.1", status: "confirmed", weight: 1, topic_code: "T3" }],
  misconceptions: ["wrong_operation"],
};
const QUALITY = {
  method_version: "aq-v1", dataset_id: "d", dataset_version: 1, current_dataset_version: 1, is_stale: false, is_synthetic: true, generated_at: "2026-11-11T10:00:00Z",
  provenance: { analysis_id: "abcdef123456", code_version: "0.1.0", kind: "assessment_quality", method_version: "aq-v1" }, assessment: ASSESSMENT,
  rules: { attempt_rule: "first", omitted_policy: "as_incorrect" },
  form: { denominators: { assigned: 612, present: 595, absent: 17, no_sitting_record: 0, n_items: 12, expected_item_responses: 7140 }, participation_rate: 0.97,
    completion_rate: 0.945, omission_rate: 0.055, missing_rate: 0, item_responses: {}, reliability: { cronbach_alpha: stat(null, "too_few_learners"),
      n_complete_learners: 20, n_items: 12, n_zero_variance_items: 0, min_learners: 30, min_items: 3 },
    score_distribution: { n: 595, mean: 0.42, median: 0.41, sd: 0.19, min: 0, max: 1, floor_share: 0.01, ceiling_share: 0, histogram: [{ from: 0, to: 0.1, count: 3 }], unavailable_reason: null } },
  slices: { language: [{ value: "kz", n: null, mean: null, median: null, sd: null, suppressed: true, suppression: "primary" }] },
  items: [ITEM], flag_counts: { negative_discrimination: 1 }, n_flagged_items: 1,
  exclusions: { absent_learners: 17, assigned_without_sitting_record: 0, rows_excluded_by_attempt_rule: 0, learners_with_repeat_attempts: 0, responses_outside_form: 0, rejected_import_rows_in_dataset: 0 },
  thresholds: {}, limitations: [msg("quality_flags_are_signals", "info")],
};

beforeEach(() => {
  routes = [];
  calls.length = 0;
  mockFetch();
});

test("measurement dictionary has a Kazakh string with the same placeholders for every key", () => {
  const ph = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(",");
  for (const key of Object.keys(mdict.ru) as (keyof typeof mdict.ru)[]) {
    expect(mdict.kz[key], key).toBeTruthy();
    expect(ph(mdict.kz[key]), key).toBe(ph(mdict.ru[key]));
  }
});

test("quality detail shows denominators, unavailable alpha with reason, suppressed slice and item flags; switches to KZ", async () => {
  routes = [[/GET .*\/quality\/assessments\/a1/, () => ({ body: QUALITY })]];
  renderAt("/quality/a1", "/quality/:assessmentId", <QualityDetailPage />);
  expect(await screen.findByText("Диагностика проверки DIAG-BASE")).toBeInTheDocument();
  expect(screen.getByText(/too_few_learners/)).toBeInTheDocument();
  expect(screen.getByText(/скрыто \(мало учеников\)/)).toBeInTheDocument();
  expect(screen.getByText("negative_discrimination")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Q05/ }));
  expect(screen.getByText("RU negative_discrimination")).toBeInTheDocument();
  expect(screen.getByText("ключ")).toBeInTheDocument();
  act(() => screen.getByText("to-kz").click());
  expect(await screen.findByText("DIAG-BASE тексеруінің диагностикасы")).toBeInTheDocument();
  expect(screen.getByText("KZ negative_discrimination")).toBeInTheDocument();
  // changing a rule re-requests with the rule in the query string
  fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "last" } });
  await waitFor(() => expect(calls.some((c) => c.url.includes("attempt_rule=last"))).toBe(true));
});

test("quality list: empty state and forbidden state", async () => {
  routes = [[/GET .*\/quality\/assessments/, () => ({ body: { method_version: "aq-v1", rules: {}, assessments: [] } })]];
  const { unmount } = renderAt("/quality", "/quality", <QualityListPage />);
  expect(await screen.findByText("Нет данных")).toBeInTheDocument();
  unmount();
  routes = [[/GET .*\/quality\/assessments/, () => ({ status: 403, body: { error: { code: "forbidden", message: "no", details: {} }, request_id: "r" } })]];
  renderAt("/quality", "/quality", <QualityListPage />);
  expect(await screen.findByText("Недостаточно прав для этого действия")).toBeInTheDocument();
});

const PILOT = {
  id: "p1", code: "PIL-M02", title: "Пилот", dataset_id: "d", status: "ready", design: "single_group", assignment_unit: "cohort",
  causal_ceiling: { code: "descriptive_change", label_ru: "Описательная динамика", label_kz: "Сипаттамалық динамика" },
  intervention_id: "iv", intervention_version_id: "v", intervention_version: 1, intervention_snapshot: { title_ru: "Взаимная проверка" }, snapshot_sha256: "abcdef1234567890",
  snapshot_locked: true, decision_id: null, topic: { code: "T3", title_ru: "Дроби", title_kz: "Бөлшек" }, objective: null, primary_outcome_ru: "Доля", cohorts: [
    { cohort_id: "c1", code: "M01-6В", school_id: "s", school_code: "M01", arm: "intervention", wave: null, n_learners: 25 }],
  randomization: null, baseline_assessment: null, outcome_assessment: null, pre_period_assessment_ids: [], start_date: "2026-09-21", end_date: "2026-10-23",
  follow_up_due: "2026-10-30", owner: "М", planned: { minutes_per_session: 20, sessions_per_week: 3, duration_weeks: 5, total_sessions: 15, total_minutes: 300 },
  inclusion_criteria: "", exclusion_criteria: "", analysis_plan: { adjustment: "none" }, validation: { ok: true, errors: [], warnings: [msg("single_group_no_causal", "info")] },
  allowed_transitions: ["draft", "active", "stopped"], events: [], latest_outcome: null, created_at: "2026-11-11T10:00:00Z", created_by: "М", is_synthetic: true,
};

test("pilot actions use server-provided transitions; stop requires a reason; the request carries the target status", async () => {
  routes = [[/GET .*\/pilots\/p1$/, () => ({ body: PILOT })], [/POST .*\/pilots\/p1\/transition/, () => ({ body: { ...PILOT, status: "active", allowed_transitions: ["completed", "stopped"] } })]];
  renderAt("/pilots/p1", "/pilots/:id", <PilotDetailPage />);
  expect(await screen.findByText("Протокол готов к переходу")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Остановить" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Запустить пилот" }));
  await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ to_status: "active", note: "" }));
  expect(screen.getByText("Описательная динамика")).toBeInTheDocument();
});

test("follow-up shows 'not interpretable' for low fidelity and never 'ineffective'", async () => {
  const outcome = {
    id: "o1", pilot_id: "p1", status: "invalid_due_to_fidelity", status_label: { code: "invalid_due_to_fidelity", label_ru: "x", label_kz: "x" },
    causal_level: { code: "none", label_ru: "Вывод невозможен", label_kz: "Қорытынды мүмкін емес" }, causal_ceiling: PILOT.causal_ceiling,
    fidelity: { code: "low", label_ru: "Низкая", label_kz: "Төмен" }, method_version: "loop-v1", dataset_version: 1, current_dataset_version: 1, is_stale: false,
    interim: false, created_at: "2026-11-11T10:00:00Z",
    result: { primary: { estimand: "mean_paired_change", estimate: 0.075, ci_low: 0.05, ci_high: 0.1, ci_unavailable_reason: null, source: "raw" },
      arms: {}, cohorts: null, status_rules_fired: ["fidelity_low"], interpretation_ru: "Результат нельзя считать проверкой интервенции — ни её эффективности, ни неэффективности.",
      comparability: { code: "identical_form" }, n_outcome_items: 12, attrition: 0.05, reasons: [msg("fidelity_low")] },
  };
  routes = [[/GET .*\/pilots\/p1$/, () => ({ body: { ...PILOT, status: "completed" } })], [/GET .*\/outcomes/, () => ({ body: [outcome] })],
    [/GET .*\/conclusions/, () => ({ body: [] })], [/GET .*\/curriculum/, () => ({ body: { assessments: [] } })]];
  renderAt("/pilots/p1/follow-up", "/pilots/:id/follow-up", <FollowUpPage />);
  expect(await screen.findByText("Не интерпретируется: реализация")).toBeInTheDocument();
  expect(screen.getByText(/ни её эффективности, ни неэффективности/)).toBeInTheDocument();
  expect(screen.getByText("Вывод и следующий цикл")).toBeInTheDocument();
  expect(screen.queryByText(/не работает/)).toBeNull();
  expect(screen.getByRole("button", { name: "Сохранить вывод" })).toBeDisabled(); // summary is required
});

test("viewer does not get drafting actions in the library", async () => {
  routes = [[/GET .*\/interventions/, () => ({ body: [] })]];
  renderAt("/interventions", "/interventions", <InterventionsPage />, ["viewer"]);
  expect(await screen.findByText("Библиотека интервенций")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Новая интервенция" })).toBeNull();
});

test("portfolio shows aggregates and no 'best intervention'", async () => {
  const pf = {
    generated_at: "x", as_of: "2026-11-11", dataset_id: null, counts_by_status: { draft: 1, ready: 0, active: 1, completed: 2, stopped: 0 },
    follow_ups: { overdue: [], due_within_14_days: [], upcoming: [] }, fidelity_distribution: { high: 1, moderate: 0, low: 1, unknown: 1 },
    outcome_distribution: { positive_signal: 1, invalid_due_to_fidelity: 1 }, interventions_with_repeated_signals: [], coverage: { topics: [] },
    missing_for_conclusions: [], action_queue: [{ pilot_id: "p2", code: "PIL-M02", title: "t", action: "record_conclusion" }], best_intervention: null,
    best_intervention_reason: "not_shown", pilots: [], limitations: [msg("no_league_tables", "info")],
  };
  routes = [[/GET .*\/portfolio\/interventions/, () => ({ body: pf })],
    [/GET .*\/learning\/summary/, () => ({ body: { interventions: [], lessons: [], open_questions: [], pending_evidence_reviews: [], note_ru: "n", note_kz: "n" } })]];
  renderAt("/portfolio/interventions", "/portfolio/interventions", <PortfolioPage />);
  expect(await screen.findByText("Сохранить вывод по результату")).toBeInTheDocument();
  expect(screen.getByText(/«Лучшая интервенция» не показывается/)).toBeInTheDocument();
  expect(screen.getByText("RU no_league_tables")).toBeInTheDocument();
});
