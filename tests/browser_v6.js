// Prueba de conexión HA en navegador, backend real del runner; sin API simulada.
const { launchBrowser } = require('./browser_support');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [origin, out] = process.argv.slice(2);
const results = { realLocalBackend: true, realHomeAssistant: false, passed: false, cases: [], pageErrors: 0 };
const check = (condition, name) => { assert.ok(condition, name); results.cases.push(name); };
const authorized = key => ({ headers: { Authorization: 'Bearer ' + key } });
(async () => {
 let browser;
 try {
  fs.mkdirSync(out, { recursive: true });
  browser = await launchBrowser();
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  page.on('pageerror', () => results.pageErrors++);
  await page.goto(origin + '/');
  await page.waitForFunction(() => document.querySelector('#main-content').getAttribute('aria-busy') === 'false');
  await page.getByRole('button', { name: 'Datos y ajustes', exact: true }).click();
  const section = page.locator('.ha-connection');
  const key = section.locator('input[type=password]');
  const btn = name => section.getByRole('button', { name, exact: true });
  const idle = () => page.waitForFunction(() => document.querySelector('.ha-connection')?.getAttribute('aria-busy') === 'false');
  await idle();
  check((await (await fetch(origin + '/api/ha/status')).json()).enabled === false, 'initial-disabled');
  check(await key.inputValue() === '' && await btn('Mostrar clave').isDisabled(), 'secret-not-loaded');
  await btn('Activar conexión').click(); await idle();
  const actual = await (await fetch(origin + '/api/ha/status')).json();
  check(actual.enabled === true && actual.has_token === true && actual.protocol_version === 1, 'enable-api-readback');
  check(await key.inputValue() === '', 'enable-no-auto-reveal');
  await btn('Mostrar clave').click(); await idle();
  const first = await key.inputValue();
  check(first.length >= 43 && await key.getAttribute('type') === 'password', 'explicit-key-is-password');
  check((await fetch(origin + '/bridge/v1/health', authorized(first))).ok, 'key-authenticates');
  await btn('Copiar clave').click(); await idle();
  check(await page.evaluate(value => navigator.clipboard.readText().then(text => text === value), first), 'clipboard-matches-without-output');
  await btn('Regenerar clave…').click();
  await page.getByRole('dialog', { name: '¿Regenerar la clave de conexión?', exact: true }).getByRole('button', { name: 'Cancelar', exact: true }).click();
  check((await fetch(origin + '/bridge/v1/health', authorized(first))).ok, 'cancel-rotation-keeps-key');
  await btn('Regenerar clave…').click();
  await page.getByRole('dialog', { name: '¿Regenerar la clave de conexión?', exact: true }).getByRole('button', { name: 'Regenerar clave', exact: true }).click(); await idle();
  check(await key.inputValue() === '' && !(await fetch(origin + '/bridge/v1/health', authorized(first))).ok, 'rotation-revokes-without-reveal');
  await btn('Mostrar clave').click(); await idle();
  const second = await key.inputValue();
  check(second !== first && (await fetch(origin + '/bridge/v1/health', authorized(second))).ok, 'new-key-authenticates');
  await page.locator('dialog[open]').last().getByRole('button', { name: 'Cerrar diálogo', exact: true }).click();
  await page.getByRole('button', { name: 'Datos y ajustes', exact: true }).click(); await idle();
  check(await key.inputValue() === '', 'close-reopen-clears-secret');
  await btn('Desactivar conexión').click(); await idle();
  check((await (await fetch(origin + '/api/ha/status')).json()).enabled === false && await key.inputValue() === '' && await key.isHidden(), 'disable-clears-secret-api-readback');
  check(!(await fetch(origin + '/bridge/v1/health', authorized(second))).ok, 'disable-blocks-key');
  check(await page.evaluate(values => !values.some(value => document.documentElement.outerHTML.includes(value) || document.body.textContent.includes(value) || JSON.stringify(localStorage).includes(value) || JSON.stringify(sessionStorage).includes(value)), [first, second]), 'no-secret-in-html-or-storage');
  for (const width of [320, 390, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    await section.getByRole('heading').scrollIntoViewIfNeeded();
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `no-overflow-${width}`);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await section.getByRole('heading').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'conexion-ha-movil.png') });
  await page.evaluate(() => navigator.clipboard.writeText(''));
  check(await page.evaluate(() => navigator.clipboard.readText().then(value => value === '')), 'test-clipboard-cleared');
  check(results.pageErrors === 0, 'no-js-errors');
  results.passed = true;
 } finally {
  if (browser) await browser.close();
  fs.writeFileSync(path.join(out, 'conexion-ha.json'), JSON.stringify(results, null, 2));
 }
 console.log(JSON.stringify(results, null, 2));
})().catch(error => { console.error('Fallo de prueba UI HA:', error.message); process.exitCode = 1; });
