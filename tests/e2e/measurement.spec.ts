/**
 * Measurement & learning loop, end to end in the browser (seeded demo; creates its own intervention and pilot):
 * quality problem → suggested interventions → new intervention (draft → reviewed) → valid pilot (ready → active)
 * → fidelity log → seeded follow-up result and conclusion → next decision version; plus the honest low-fidelity
 * result of PIL-M02 and the portfolio without a "best intervention".
 */
import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByTestId("enter-demo").click();
  await page.getByTestId("choose-measurement_loop").click();
}

async function pickByPrefix(page: Page, label: string, prefix: string) {
  const sel = page.getByLabel(label, { exact: true });
  const value = await sel.evaluate((el: HTMLSelectElement, p: string) => [...el.options].find((o) => o.textContent!.startsWith(p))!.value, prefix);
  await sel.selectOption(value);
}

test("quality → intervention → pilot → fidelity → follow-up → next decision", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);

  // 1. quality problem
  await page.getByRole("link", { name: "Качество проверок" }).click();
  await page.getByTestId("quality-list").getByRole("link", { name: "DIAG-BASE" }).click();
  await expect(page.getByTestId("item-Q05")).toContainText("отрицательная различающая способность");
  await page.getByTestId("item-Q05").getByRole("button").click();
  await expect(page.getByText(/Отрицательная различающая способность/)).toBeVisible();

  // 2. suggestions with explained scores
  await page.getByRole("button", { name: "Подобрать интервенцию" }).click();
  await expect(page.getByTestId("suggestions")).toContainText("INT-STRIPS");

  // 3. new intervention, reviewed
  const code = `E2E-${Date.now()}`;
  await page.getByRole("button", { name: "Новая интервенция" }).click();
  await page.getByLabel("Код", { exact: true }).fill(code);
  await page.getByLabel("Название (RU)").fill("Интервенция из e2e");
  await page.getByLabel("Инструкция").fill("Шаги занятия");
  await page.getByLabel("Цели", { exact: true }).selectOption("misconception");
  await page.getByLabel("Типичная ошибка").selectOption("add_across");
  await page.getByRole("button", { name: "Добавить цель" }).click();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await page.getByRole("button", { name: "Утвердить (рецензия)" }).click();
  await expect(page.getByText(/Версия рецензирована и не изменяется/)).toBeVisible();

  // 4. valid pilot
  await page.getByRole("button", { name: "Запустить пилот" }).click();
  await page.getByLabel("Название пилота").fill("Пилот e2e");
  await page.getByLabel("Ответственный").fill("Методист");
  await pickByPrefix(page, "Тема", "T3 ");
  await page.getByLabel("Основной результат").fill("Доля баллов T3");
  await page.getByLabel("Группа M02-6Г").selectOption("intervention");
  await pickByPrefix(page, "Входное измерение", "DIAG-END");
  await page.getByLabel("Начало").fill("2026-11-02");
  await page.getByLabel("Окончание").fill("2027-01-29");
  await page.getByLabel("Срок повторного измерения").fill("2027-02-05");
  await page.getByRole("button", { name: "Сохранить черновик протокола" }).click();
  await expect(page.getByText("Протокол готов к переходу")).toBeVisible();
  await page.getByRole("button", { name: "Протокол готов" }).click();
  await page.getByRole("button", { name: "Запустить пилот" }).click();
  await expect(page.getByText("активен").first()).toBeVisible();

  // 5. fidelity log
  await page.getByRole("button", { name: "Журнал реализации" }).click();
  await page.getByRole("button", { name: "Добавить запись" }).click();
  await page.getByLabel("Дата").fill("2026-11-03");
  await page.locator('form[aria-label="Добавить запись"]').getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("fidelity-cohorts")).toContainText("M02-6Г");

  // 6. seeded completed pilot: honest result, conclusion, next decision version
  await page.getByRole("link", { name: "Портфель пилотов" }).click();
  await expect(page.getByText(/«Лучшая интервенция» не показывается/)).toBeVisible();
  await page.getByTestId("pilots").getByRole("link", { name: "PIL-M02" }).click();
  await page.getByRole("button", { name: "Повторное измерение" }).click();
  await expect(page.getByTestId("outcome")).toContainText("Не интерпретируется: реализация");
  await expect(page.getByTestId("outcome")).toContainText("ни её эффективности, ни неэффективности");
  await page.getByLabel("Решение", { exact: true }).selectOption("extend_data_collection");
  await page.getByLabel("Вывод (что показали данные)").fill("Реализация низкая: эффективность не проверена; повторить с поддержкой учителей.");
  await page.getByLabel("Открытые вопросы (по одному в строке)").fill("Что мешало проводить занятия?");
  await page.getByRole("button", { name: "Сохранить вывод" }).click();
  await expect(page.getByTestId("conclusions")).toContainText("Что мешало проводить занятия?");
  await page.getByTestId("conclusions").getByRole("link", { name: "Открыть новую версию решения" }).first().click();
  await expect(page.getByTestId("decision-detail")).toContainText("Классы пилота PIL-M02");

  // 7. KZ
  await page.getByRole("link", { name: "Портфель пилотов" }).click();
  await page.getByRole("button", { name: "KZ" }).click();
  await expect(page.getByRole("heading", { name: "Пилоттар портфелі" })).toBeVisible();
  await page.getByRole("button", { name: "RU" }).click();
  expect(errors).toEqual([]);
});

test("keyboard: list links are reachable with Tab and open with Enter; focus is visible", async ({ page }) => {
  await login(page);
  for (const [nav, table] of [["Качество проверок", "quality-list"], ["Интервенции", "interventions"], ["Портфель пилотов", "pilots"]] as const) {
    await page.getByRole("link", { name: nav }).click();
    const first = page.getByTestId(table).getByRole("link").first();
    await expect(first).toBeVisible();
    const href = await first.getAttribute("href");
    let reached = false;
    for (let i = 0; i < 80 && !reached; i++) {  // real keyboard navigation, not element.focus()
      await page.keyboard.press("Tab");
      reached = await first.evaluate((el) => el === document.activeElement);
    }
    expect(reached).toBe(true);
    const outline = await first.evaluate((el) => getComputedStyle(el).boxShadow + getComputedStyle(el).outlineStyle);
    expect(outline).not.toBe("nonenone"); // :focus-visible ring
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`${href}$`));
    await page.goBack();
  }
  // the decision created from a pilot conclusion shows the learning-loop block with a link back to the outcome
  await page.getByRole("link", { name: "Портфель пилотов" }).click();
  await page.getByTestId("pilots").getByRole("link", { name: /PIL-M01/ }).click();
  await page.getByRole("button", { name: "Повторное измерение" }).click();
  await page.getByTestId("conclusions").getByRole("link", { name: "Открыть новую версию решения" }).first().click();
  await expect(page.getByTestId("learning-loop")).toContainText("PIL-M01");
  await expect(page.getByTestId("learning-loop")).toContainText("INT-STRIPS");
  await page.getByTestId("learning-loop").getByRole("link", { name: "Открыть результат пилота" }).press("Enter");
  await expect(page.getByTestId("outcome")).toBeVisible();
});
