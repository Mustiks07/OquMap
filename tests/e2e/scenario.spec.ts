/**
 * End-to-end methodist scenario on a freshly seeded demo database (see README → "Сквозной тест"):
 * login → dataset → quality → overview → RU/KZ keeps filters → topic → comparison → planner (plan + conflict)
 * → decision (AI draft, save, approve) → PDF export → follow-up import → dynamics → assistant → import report.
 */
import { expect, test, type Page } from "@playwright/test";
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const REPO = path.resolve(__dirname, "../..");

async function login(page: Page) {
  await page.goto("/login");
  await page.getByTestId("enter-demo").click();
  // one click opens the recommended scenario directly on the overview
  await expect(page.getByTestId("topics-table")).toBeVisible({ timeout: 60_000 });
}

test("full methodist path", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await expect(page.getByTestId("dataset-chip")).toContainText("Синтетические данные");

  await expect(page.getByTestId("guide-overview")).toHaveAttribute("data-done", "1");
  // overview + filters survive a language switch
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
  await page.getByRole("link", { name: "Сравнение изданий", exact: true }).click();
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
  await expect(page.getByTestId("guide-followup")).toHaveAttribute("data-done", "1");
  await page.reload();
  await expect(page.getByTestId("guide-followup")).toHaveAttribute("data-done", "1"); // progress survives reload
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

test("structural import blocks a broken item bank and lists rejected rows", async ({ page }) => {
  await login(page);
  await page.getByTestId("nav-import").click();
  await page.getByTestId("project-name").fill("Проверка ошибок импорта");
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("project-name")).toHaveValue(""); // project created and selected
  await page.getByTestId("stage-program").click();
  await page.getByTestId("import-file").setInputFiles(path.join(REPO, "data/templates/example_project/1_program.csv"));
  await page.getByTestId("import-validate").click();
  await expect(page.getByTestId("rows-rejected")).toHaveText("0");
  await page.getByTestId("import-commit").click();
  await expect(page.getByText(/Загружено\. Новая версия данных/)).toBeVisible({ timeout: 90_000 });
  await page.getByTestId("stage-item_bank").click();
  const bank = readFileSync(path.join(REPO, "data/templates/example_project/3_item_bank.csv"), "utf-8")
    .replace("Вычислите 248 + 175", '=HYPERLINK(""http://x"")').replace("EX-1.2,confirmed", "EX-9.9,confirmed");
  await page.getByTestId("import-file").setInputFiles({ name: "bank.csv", mimeType: "text/csv", buffer: Buffer.from(bank) });
  await page.getByTestId("import-validate").click();
  await expect(page.locator("#import-report")).toContainText("formula_not_allowed");
  await expect(page.locator("#import-report")).toContainText("unknown_objective");
  await expect(page.getByTestId("import-commit")).toBeDisabled();
});

test("empty organisation imports a real project from templates and analyses it", async ({ page }) => {
  const cmd = process.env.OQUMAP_CREATE_ORG_CMD ??
    "docker compose -f ../../docker-compose.yml exec -T -e OQUMAP_ADMIN_PASSWORD api python -m oqumap.admin create-org";
  const user = `e2e.${Date.now().toString(36)}`;
  const password = "E2e-Password-2026";
  execSync(`${cmd} --name "E2E организация" --admin ${user}`, { env: { ...process.env, OQUMAP_ADMIN_PASSWORD: password }, cwd: __dirname, stdio: "pipe" });
  await page.goto("/login");
  await page.getByLabel("Имя пользователя").fill(user);
  await page.getByLabel("Пароль").fill(password);
  await page.getByTestId("sign-in").click();
  await page.getByTestId("own-data").click();
  await page.getByTestId("project-name").fill("Математика 5 (реальный проект)");
  await page.getByTestId("create-project").click();
  await expect(page.getByTestId("project-name")).toHaveValue(""); // project created and selected
  for (const [stage, file] of [["program", "1_program.csv"], ["editions", "2_editions.csv"], ["item_bank", "3_item_bank.csv"],
                               ["roster", "4_roster.csv"], ["responses", "5_responses.csv"]]) {
    await page.getByTestId(`stage-${stage}`).click();
    await page.getByTestId("import-file").setInputFiles(path.join(REPO, "data/templates/example_project", file));
    await page.getByTestId("import-validate").click();
    await expect(page.getByTestId("rows-rejected")).toHaveText("0");
    await page.getByTestId("import-commit").click();
    await expect(page.getByText(/Загружено\. Новая версия данных/)).toBeVisible({ timeout: 90_000 });
  }
  const stageRows = page.getByTestId("stages").locator("tbody tr");
  for (let i = 0; i < 5; i++) await expect(stageRows.nth(i)).toContainText("загружено");
  await expect(stageRows.nth(5)).toContainText("необязательно");
  await expect(stageRows.nth(5)).toContainText("ожидает");
  await page.getByRole("link", { name: /Обзор тем/ }).click();
  await expect(page.getByTestId("topics-table")).toContainText("EX-T2");
  await expect(page.getByTestId("topics-table")).not.toContainText("DEMO-");
  await page.getByRole("link", { name: "Сравнение изданий", exact: true }).click();
  await expect(page.getByTestId("comparison-table")).toBeVisible();
});
