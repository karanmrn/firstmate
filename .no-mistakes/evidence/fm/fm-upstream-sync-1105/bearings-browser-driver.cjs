const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('./browser/node_modules/playwright');

(async () => {
  const evidence = '~/.no-mistakes/evidence/01M6P2V422HSKW40WQJTDHX3GD';
  const expected = fs.readFileSync(path.join(__dirname, 'holds/expected-question.txt'), 'utf8');
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const [name, width, height] of [['desktop', 1280, 900], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto('file://' + evidence + '/bearings-rendered.html');
      await page.locator('#bb-call form').waitFor();
      const text = await page.locator('#bb-call').textContent();
      if (!text.includes(expected)) throw new Error(name + ': question or final option was truncated');
      await page.getByLabel('Defer until tomorrow', { exact: true }).check();
      if (!await page.getByLabel('Defer until tomorrow', { exact: true }).isChecked()) {
        throw new Error(name + ': the final option could not be selected');
      }
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: evidence + '/bearings-' + name + '.png', fullPage: true });
      const layout = await page.evaluate(() => ({
        viewport: innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        outside: Array.from(document.querySelectorAll('body *')).filter(e => e.getBoundingClientRect().right > innerWidth + 1).map(e => ({tag: e.tagName, class: e.className, right: e.getBoundingClientRect().right, text: e.textContent.slice(0,80)})).slice(0,12)
      }));
      console.log(name + ': ' + JSON.stringify(layout));
      if (layout.scrollWidth > width) throw new Error(name + ': horizontal page overflow');
      console.log(name + ': full original question visible, final option selectable, no horizontal overflow');
    }
    if (errors.length) throw new Error(errors.join('\n'));
    console.log('Chromium: ' + browser.version());
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
