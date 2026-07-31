import { chromium } from "playwright";

const url = process.argv[2];
const executablePath = process.argv[3];
if (!url || !executablePath) {
  throw new Error("usage: node backend_xy_live_toolbar_probe.mjs URL CHROMIUM");
}

const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});

const result = {};
try {
  const page = await browser.newPage({ viewport: { width: 700, height: 520 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.goto(url, { waitUntil: "load", timeout: 30_000 });

  const canvas = page.locator(".xy-matplotlib-canvas");
  const toolbar = page.locator(".xy-matplotlib-toolbar");
  const status = page.locator(".xy-matplotlib-status");
  const button = (action) =>
    toolbar.locator(`[data-xy-toolbar-action="${action}"]`);
  await canvas.waitFor({ state: "visible" });
  await toolbar.waitFor({ state: "visible" });

  result.controls = await toolbar.locator("button").allTextContents();
  result.backInitiallyDisabled = await button("back").isDisabled();
  result.forwardInitiallyDisabled = await button("forward").isDisabled();

  const bounds = await canvas.boundingBox();
  if (!bounds) throw new Error("live XY canvas has no browser bounds");
  const center = {
    x: bounds.x + bounds.width * 0.5,
    y: bounds.y + bounds.height * 0.5,
  };
  await page.mouse.move(center.x, center.y);
  await page.waitForFunction(
    () =>
      document.querySelector(".xy-matplotlib-status")?.textContent.includes("$5.0M") &&
      getComputedStyle(document.querySelector(".xy-matplotlib-canvas")).cursor === "crosshair",
  );
  result.coords = await status.textContent();
  result.cursor = await canvas.evaluate((element) => getComputedStyle(element).cursor);

  await button("pan").click();
  await page.waitForFunction(
    () =>
      document
        .querySelector('[data-xy-toolbar-action="pan"]')
        ?.getAttribute("aria-pressed") === "true",
  );
  result.panPressed = await button("pan").getAttribute("aria-pressed");

  await page.mouse.move(center.x, center.y);
  await page.waitForFunction(
    () => getComputedStyle(document.querySelector(".xy-matplotlib-canvas")).cursor === "move",
  );
  result.panCursor = await canvas.evaluate((element) => getComputedStyle(element).cursor);
  await page.mouse.down();
  await page.mouse.move(center.x + bounds.width * 0.12, center.y, { steps: 4 });
  await page.mouse.up();
  await page.waitForFunction(
    () => !document.querySelector('[data-xy-toolbar-action="back"]')?.disabled,
  );
  result.backAfterPanEnabled = !(await button("back").isDisabled());

  await button("pan").click();
  await page.waitForFunction(
    () =>
      document
        .querySelector('[data-xy-toolbar-action="pan"]')
        ?.getAttribute("aria-pressed") === "false",
  );
  await button("back").click();
  await page.waitForFunction(
    () => !document.querySelector('[data-xy-toolbar-action="forward"]')?.disabled,
  );
  result.forwardAfterBackEnabled = !(await button("forward").isDisabled());

  await button("forward").click();
  await page.waitForFunction(
    () =>
      !document.querySelector('[data-xy-toolbar-action="back"]')?.disabled &&
      document.querySelector('[data-xy-toolbar-action="forward"]')?.disabled,
  );
  result.backAfterForwardEnabled = !(await button("back").isDisabled());
  result.forwardAfterForwardDisabled = await button("forward").isDisabled();
  result.pageErrors = pageErrors;
} finally {
  await browser.close();
}

process.stdout.write(`${JSON.stringify(result)}\n`);
