import { expect, test, type Page, type TestInfo } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByTestId("enter-demo").click();
  await expect(page.getByTestId("topics-table")).toBeVisible({ timeout: 60_000 });
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(overflow.document, `document width ${overflow.document}px exceeds viewport ${overflow.viewport}px`).toBeLessThanOrEqual(overflow.viewport + 1);
}

async function captureAtlas(page: Page, testInfo: TestInfo, name: string) {
  await expect(page.getByTestId("graph-path")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#atlas-question")).toBeVisible();
  await expect(page.locator(".atlas-inspector")).toBeVisible();
  await expect(page.locator(".atlas-decision-dock")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  const font = await page.locator("body").evaluate((element) => getComputedStyle(element).fontFamily);
  expect(font.toLowerCase()).toContain("onest");
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
}

test("evidence atlas keeps its hierarchy at jury-screen sizes in RU and KZ", async ({ page }, testInfo) => {
  await login(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("overview-ru-1440.png"), fullPage: true });
  await page.goto("/graph");

  await captureAtlas(page, testInfo, "atlas-ru-1440");

  await page.setViewportSize({ width: 1280, height: 800 });
  await captureAtlas(page, testInfo, "atlas-ru-1280");

  await page.getByRole("button", { name: "KZ" }).click();
  await expect(page.locator("#atlas-question")).toContainText("неге төмен");
  await captureAtlas(page, testInfo, "atlas-kz-1280");
});
