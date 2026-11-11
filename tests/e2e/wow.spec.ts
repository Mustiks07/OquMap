/**
 * WOW layer end to end: the read-only "Демо за 3 минуты" route (preflight → 7 screens, each answering
 * found / trust / next; reload keeps the step; reset gives a fresh demo tenant), plus graph → council,
 * sandbox and quiz review on the same disposable tenant.
 */
import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByTestId("enter-demo").click();
  await expect(page.getByTestId("topics-table")).toBeVisible({ timeout: 60_000 });
}

test("demo in 3 minutes: preflight and seven read-only screens", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await page.getByTestId("nav-tour").click();
  await expect(page.getByTestId("tour-preflight")).toContainText("Готово к показу");
  for (let i = 1; i <= 7; i++) {
    await expect(page.getByTestId(`tour-step-${i}`)).toHaveAttribute("aria-current", "step");
    for (const id of ["tour-found", "tour-trust", "tour-next-action"]) await expect(page.getByTestId(id)).not.toBeEmpty();
    if (i === 1) await expect(page.getByTestId("tour-found")).toContainText("T3");
    if (i === 2) {
      await expect(page.getByTestId("evidence-graph")).toBeVisible();
      await page.locator("[data-kind=item]").first().click();
      await expect(page.getByTestId("item-rows")).toBeVisible();
    }
    if (i === 3) {
      await expect(page.getByTestId("tour-raw")).toContainText("−");
      await expect(page.getByTestId("tour-adjusted")).toContainText("+");
      // reload keeps the presentation step
      await page.reload();
      await expect(page.getByTestId("tour-step-3")).toHaveAttribute("aria-current", "step");
    }
    if (i === 4) {
      await expect(page.getByTestId("council-highlight")).toContainText("Без поправки");
      await expect(page.getByTestId("council-final")).toContainText("не эффект пособия");
    }
    if (i === 5) await expect(page.getByTestId("tour-sandbox")).toContainText("Ограничения несовместимы");
    if (i === 6) await expect(page.getByTestId("tour-quiz")).toContainText("Q1");
    if (i < 7) await page.getByTestId("tour-next").click();
  }
  // reset: a fresh disposable tenant, back to step 1
  const before = await page.evaluate(() => localStorage.getItem("oqumap.token"));
  await page.getByTestId("tour-reset").click();
  await expect(page.getByTestId("tour-step-1")).toHaveAttribute("aria-current", "step");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("oqumap.token")), { timeout: 60_000 }).not.toBe(before);
  expect(errors).toEqual([]);
});

test("graph → council, sandbox scenarios, quiz review", async ({ page }) => {
  await login(page);
  await page.getByTestId("nav-graph").click();
  await expect(page.getByTestId("graph-path")).toContainText("Пробел");
  await page.getByTestId("run-council").click();
  await expect(page.getByTestId("council-claims")).toContainText("заблокировано");

  await page.goto("/sandbox");
  await page.getByTestId("sandbox-text").fill("добавь 2 часа на T3 за счёт T7, T5 не трогать");
  await page.getByTestId("sandbox-preview").click();
  await expect(page.getByTestId("sandbox-diff")).toContainText("T7");
  await page.getByTestId("sandbox-add").click();
  await page.getByTestId("sandbox-run").click();
  await expect(page.getByTestId("sandbox-table")).toContainText("(+2)");
  await page.getByTestId("sandbox-to-decision").click();
  await expect(page).toHaveURL(/decisions/);

  await page.goto("/quizzes");
  await page.getByTestId("quiz-generate").click();
  await expect(page.getByTestId("quiz-editor")).toContainText("Все обязательные проверки пройдены");
  await page.getByTestId("quiz-edit").click();
  await page.getByLabel("Q1 условие").fill("Вычислите и запишите решение: 1/2 + 1/3.");
  await page.getByTestId("quiz-save").click();
  await expect(page.getByTestId("quiz-blocking")).toContainText("Q1:key_recomputed");
  await expect(page.getByTestId("quiz-approve")).toBeDisabled();
  await page.getByTestId("quiz-edit").click();
  await page.getByTestId("verify-Q1").check();
  await page.getByTestId("quiz-save").click();
  await page.getByTestId("quiz-approve").click();
  await expect(page.getByTestId("quiz-responses")).toBeVisible();
});

test("language filter shows the Kazakh-medium classes", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("enter-demo").click();
  await expect(page.getByTestId("topics-table")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("overview-counts")).toContainText("32");
  await page.getByLabel("Язык обучения").selectOption("kz");
  await expect(page.getByTestId("overview-counts")).toContainText("3 класс");
  await page.getByRole("button", { name: "KZ" }).click();
  await expect(page.getByLabel("Оқыту тілі")).toHaveValue("kz");
});
