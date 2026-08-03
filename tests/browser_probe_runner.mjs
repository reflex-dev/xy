import { chromium } from "playwright";

const [executablePath, pageUrl, resultAttribute] = process.argv.slice(2);
if (!executablePath || !pageUrl || !resultAttribute) {
  throw new Error(
    "usage: node browser_probe_runner.mjs CHROMIUM PAGE_URL RESULT_ATTRIBUTE",
  );
}

const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--allow-file-access-from-files",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
  ],
});

try {
  const page = await browser.newPage({ viewport: { width: 640, height: 480 } });
  await page.goto(pageUrl, { waitUntil: "load", timeout: 30_000 });
  const errorAttribute = `${resultAttribute}-error`;
  try {
    await page.waitForFunction(
      ([result, error]) =>
        Boolean(
          document.body?.hasAttribute(result) || document.body?.hasAttribute(error),
        ),
      [resultAttribute, errorAttribute],
      { timeout: 10_000 },
    );
  } catch {
    // Return the current DOM.  The Python harness reports the missing result
    // and retains its bounded retry policy, with none of Chromium CLI's
    // first-profile `--dump-dom` shutdown hangs.
  }
  process.stdout.write(await page.content());
} finally {
  await browser.close();
}
