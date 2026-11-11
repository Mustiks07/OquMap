/**
 * End-to-end methodist scenario on a freshly seeded demo database (see README → "Сквозной тест"):
 * login → dataset → quality → overview → RU/KZ keeps filters → topic → comparison → planner (plan + conflict)
 * → decision (AI draft, save, approve) → PDF export → follow-up import → dynamics → assistant → import report.
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const REPO = path.resolve(__dirname, "../..");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByTestId("enter-demo").click();
  await page.getByTestId("choose-base").click();
  await expect(page.locator("#quality")).toBeVisible();
}

test("full methodist path", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await expect(page.getByTestId("dataset-chip")).toContainText("Синтетические данные");

  // overview + filters survive a language switch
  await page.getByRole("link", { name: /Обзор тем/ }).click();
  await expect(page.getByTestId("topics-table")).toBeVisible();
  await page.getByLabel("Правило попыток").selectOption("last");
  await expect(page.getByTestId("overview-counts")).toBeVisible();
  await page.getByRole("button", { name: "KZ" }).click();
  await expect(page.getByRole("heading", { name: /Бағдарламаға/ })).toBeVisible();
  await expect(page.getByLabel("Әрекет ережесі")).toHaveValue("last");
  await page.getByRole("button", { name: "RU" }).click();
  await expect(page.getByLabel("Правило попыток")).toHaveValue("last");
  await page.getByLabel("Правило попыток").selectOption("first");

  // topic
  await page.getByTestId("open-topic-T3").click();
  await expect(page.getByTestId("topic-title")).toContainText("T3");
  await expect(page.getByTestId("topic-score")).toContainText("%");
  await page.getByTestId("interpret-add_across").click();
  await expect(page.getByText("Записанный демо-пример").first()).toBeVisible();

  // comparison: composition flips the sign
  await page.getByRole("link", { name: /Сравнение изданий/ }).click();
  await expect(page.getByTestId("comparison-table")).toBeVisible();
  await expect(page.getByTestId("adjusted-diff")).toContainText("+");
  await expect(page.getByText("Направление разницы изменилось")).toBeVisible();
  await page.getByTestId("use-comparison").click();

  // planner
  await page.getByRole("link", { name: /Планировщик/ }).click();
  await expect(page.getByTestId("planner-table")).toBeVisible();
  await page.getByTestId("solve").click();
  await expect(page.getByTestId("scenario-balanced")).toContainText("optimal");
  await page.getByTestId("use-plan-balanced").click();

  // decision
  await page.getByRole("link", { name: /Решение и отчёт/ }).click();
  await expect(page.getByTestId("draft-refs")).toContainText("Сбалансированный");
  await page.getByTestId("draft-ai").click();
  await expect(page.getByTestId("f-problem")).not.toHaveValue("");
  await page.getByTestId("f-responsible").fill("Руководитель МО математики");
  await page.getByTestId("save-decision").click();
  await expect(page.getByTestId("decision-detail")).toBeVisible();
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("decision-detail")).toContainText("Утверждено");

  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-pdf").click()]);
  const pdf = readFileSync((await dl.path())!);
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");

  // follow-up: upload the synthetic follow-up file into the same dataset, then compute dynamics
  await page.getByTestId("import-file").setInputFiles(path.join(REPO, "data/demo/imports/followup_2026_2027.csv"));
  await page.getByTestId("import-validate").click();
  await expect(page.getByTestId("rows-rejected")).toHaveText("0");
  await page.getByTestId("import-commit").click();
  await expect(page.getByText(/Загружено\. Новая версия данных/)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Анализ устарел").or(page.getByText("Данные изменились после подготовки")).first()).toBeVisible();
  await page.getByTestId("run-followup").click();
  await expect(page.getByTestId("followup-result")).toBeVisible();
  await expect(page.getByTestId("followup-result")).toContainText("наблюдаемая динамика");

  // assistant receives current context
  await page.getByRole("button", { name: "Ассистент" }).click();
  await page.getByTestId("assistant").getByRole("button", { name: "Какие данные подтверждают проблему?" }).click();
  await expect(page.getByTestId("assistant").getByText("Шаблон без модели")).toBeVisible();

  expect(errors).toEqual([]);
});

test("planner shows a verified conflict", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: /Планировщик/ }).click();
  await page.getByRole("tab", { name: /Учебный модуль 20 ч/ }).click();
  for (const code of ["R", "CONS", "CHECK"]) await page.getByTestId(`fixed-${code}`).check();
  await page.getByTestId("min-TARGET").fill("10");
  await page.getByTestId("solve").click();
  await expect(page.getByTestId("conflict").first()).toContainText("Общий бюджет часов = 20");
});

test("import report lists rejected rows and never turns them into zeros", async ({ page }) => {
  await login(page);
  await page.getByLabel("Куда загрузить").selectOption("new");
  await page.getByTestId("import-file").setInputFiles(path.join(REPO, "data/demo/imports/upload_sample_with_errors.csv"));
  await page.getByTestId("import-validate").click();
  await expect(page.getByTestId("rows-rejected")).toHaveText("10");
  await expect(page.locator("#import-report")).toContainText("unknown_item");
  await expect(page.locator("#import-report")).toContainText("duplicate_row");
});
