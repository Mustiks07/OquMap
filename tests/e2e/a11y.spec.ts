/**
 * Accessibility smoke (axe-core, WCAG 2.1 A/AA rules): no serious or critical violations on the main screens,
 * including the new graph, sandbox, quiz and presentation routes, in RU and KZ.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function check(page: Page, label: string) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${label}: ${v.id} (${v.nodes.length}) ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
}

test("main screens have no serious accessibility violations", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByTestId("enter-demo")).toBeVisible();
  await check(page, "login");
  await page.getByTestId("enter-demo").click();
  await expect(page.getByTestId("topics-table")).toBeVisible({ timeout: 60_000 });
  await check(page, "overview");
  const routes: [string, string][] = [["/graph", "graph-path"], ["/sandbox", "sandbox-text"], ["/quizzes", "quiz-generate"],
    ["/demo-3min", "tour-found"], ["/decisions", "main"]];
  for (const [path, id] of routes) {
    await page.goto(path);
    if (id === "main") await expect(page.locator("main")).toBeVisible();
    else await expect(page.getByTestId(id)).toBeVisible({ timeout: 30_000 });
    await check(page, path);
  }
  await page.getByRole("button", { name: "KZ" }).click();
  await page.goto("/graph");
  await expect(page.getByTestId("graph-path")).toBeVisible();
  await check(page, "graph-kz");
});
