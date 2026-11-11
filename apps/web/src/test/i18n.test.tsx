import { act, render, screen } from "@testing-library/react";
import { dictionaries } from "../i18n/dict";
import { I18nProvider, useI18n, format } from "../i18n/I18n";
import { AppStateProvider, useAppState } from "../state/AppState";
import { pct, pp } from "../ui/format";

test("every dictionary key has a non-empty Kazakh string with the same placeholders", () => {
  const ru = dictionaries.ru;
  const kz = dictionaries.kz;
  for (const key of Object.keys(ru) as (keyof typeof ru)[]) {
    expect(kz[key], key).toBeTruthy();
    const ph = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(",");
    expect(ph(kz[key]), key).toBe(ph(ru[key]));
  }
});

test("format helpers keep shares as shares and label percentage points", () => {
  expect(pct(0.471)).toMatch(/47,1\s?%/);
  expect(pp(0.052)).toBe("+5,2 п.п.");
  expect(pp(-0.053)).toBe("−5,3 п.п.");
  expect(pp(-0.053, "kz")).toContain("п.т.");
  expect(pct(null)).toBe("—");
  expect(format("{a} из {b}", { a: 1, b: 2 })).toBe("1 из 2");
});

function Probe() {
  const { t, setLang, lang } = useI18n();
  const { filters, setFilters } = useAppState();
  return (
    <div>
      <span data-testid="label">{t("filters.attempt")}</span>
      <span data-testid="rule">{filters.attempt_rule}</span>
      <span data-testid="lang">{lang}</span>
      <button onClick={() => setFilters({ ...filters, attempt_rule: "last" })}>set</button>
      <button onClick={() => setLang(lang === "ru" ? "kz" : "ru")}>lang</button>
    </div>
  );
}

test("switching RU/KZ keeps the analysis filters", () => {
  localStorage.clear();
  render(
    <I18nProvider initial="ru">
      <AppStateProvider>
        <Probe />
      </AppStateProvider>
    </I18nProvider>,
  );
  act(() => screen.getByText("set").click());
  expect(screen.getByTestId("rule").textContent).toBe("last");
  act(() => screen.getByText("lang").click());
  expect(screen.getByTestId("lang").textContent).toBe("kz");
  expect(screen.getByTestId("label").textContent).toBe("Әрекет ережесі");
  expect(screen.getByTestId("rule").textContent).toBe("last");
});
