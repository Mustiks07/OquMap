/** Weekly calendar: current calendar visible, proposed calendar with explained moves, and a verified conflict. */
import { expect, test } from "@playwright/test";

test("weekly calendar: compare, explain moves, conflict", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("enter-demo").click();
  await expect(page.getByTestId("topics-table")).toBeVisible({ timeout: 60_000 });
  await page.getByTestId("nav-calendar").click();
  await expect(page.getByTestId("cal-gantt")).toContainText("T3");
  await page.getByText("Часы тем и закреплённые недели").click();
  await page.getByTestId("cal-hours-T3").fill("18");
  await page.getByTestId("cal-holidays").fill("8, 12, 17, 18, 29");
  await page.getByTestId("cal-solve").click();
  await expect(page.getByTestId("cal-moves")).toContainText("часы темы изменились: 14 → 18 ч");
  await expect(page.getByTestId("cal-moves")).toContainText("недоступны недели 12");
  await expect(page.getByTestId("cal-load")).toBeVisible();
  await page.getByTestId("cal-hours-T3").fill("");
  await page.getByTestId("cal-from-T3").fill("2");
  await page.getByTestId("cal-to-T3").fill("4");
  await page.getByTestId("cal-solve").click();
  await expect(page.getByTestId("cal-conflict")).toContainText("Нужно 14 ч");
  await expect(page.getByTestId("cal-conflict")).toContainText("только недели 2–4");
});
