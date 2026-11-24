// Backend real conectado a una fixture de transporte Supervisor, nunca Core real.
// Uso: node tests/browser_auto_setup.js <origin> <out> --supervisor-fixture
// El runner debe arrancar la app con /data nuevo y una fixture que acepte discovery.
// No intercepta respuestas HTTP ni instala/arranca una fixture por su cuenta.
const { launchBrowser } = require('./browser_support');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [origin, out, fixtureFlag] = process.argv.slice(2);
const results = { realLocalBackend: true, supervisorTransportFixture: true, realSupervisor: false, realHomeAssistant: false, passed: false, cases: [], pageErrors: 0 };
const check = (condition, name) => { assert.ok(condition, name); results.cases.push(name); };
const states = new Set(['unavailable', 'pending', 'announced', 'error', 'disabled']);
async function status() {
  const response = await fetch(origin + '/api/ha/status');
  assert.ok(response.ok, 'status-http-ok');
  const value = await response.json();
  assert.ok(typeof value.enabled === 'boolean' && typeof value.has_token === 'boolean' && typeof value.automatic === 'boolean' && typeof value.base_url === 'string' && value.protocol_version === 1 && states.has(value.discovery_state), 'status-contract');
  assert.ok(!Object.hasOwn(value, 'api_key') && !Object.hasOwn(value, 'token'), 'status-no-secret');
  return value;
}
async function waitAnnounced() {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const value = await status();
    if (value.enabled && value.automatic && value.discovery_state === 'announced') return value;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('La fixture Supervisor no ha aceptado el anuncio en 20 segundos.');
}
(async () => {
  assert.ok(origin && out && fixtureFlag === '--supervisor-fixture', 'Requiere origin, out y --supervisor-fixture; no usar contra una instalación del usuario.');
  fs.mkdirSync(out, { recursive: true });
  let browser;
  let tokenRequests = 0;
  let rotations = 0;
  try {
    const initial = await waitAnnounced();
    check(initial.enabled && initial.has_token && initial.automatic, 'supervised-new-install-enabled-with-token');
    browser = await launchBrowser();
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    page.on('pageerror', () => results.pageErrors++);
    page.on('request', request => {
      const pathname = new URL(request.url()).pathname;
      if (pathname.endsWith('/api/ha/token')) tokenRequests++;
      if (pathname.endsWith('/api/ha/rotate') && request.method() === 'POST') rotations++;
    });
    await page.goto(origin + '/');
    await page.waitForFunction(() => document.querySelector('#main-content')?.getAttribute('aria-busy') === 'false');
    await page.getByRole('button', { name: 'Datos y ajustes', exact: true }).click();
    const section = page.locator('.ha-connection');
    const manual = section.locator('details');
    const btn = name => section.getByRole('button', { name, exact: true });
    const idle = () => page.waitForFunction(() => document.querySelector('.ha-connection')?.getAttribute('aria-busy') === 'false');
    await idle();
    check(await section.getAttribute('data-automatic') === 'true' && await section.getAttribute('data-discovery-state') === 'announced', 'automatic-announced-status');
    check((await section.innerText()).includes('no confirma que Home Assistant Core'), 'announcement-is-not-core-ack');
    check((await section.innerText()).includes('1.1.0') && (await section.innerText()).includes('reinicia Home Assistant Core'), 'component-and-core-restart-explained');
    check((await section.innerText()).includes('solo en las opciones de la integración de Home Assistant Core'), 'telegram-options-only-in-core');
    check(!await manual.evaluate(node => node.open) && await section.locator('input:visible').count() === 0, 'normal-ui-has-no-fields');
    check(await btn('Mostrar clave').isHidden() && await btn('Copiar clave').isHidden() && await btn('Regenerar clave…').isHidden(), 'manual-controls-only-in-details');
    await btn('Actualizar estado').click(); await idle();
    check(tokenRequests === 0, 'refresh-never-fetches-key');
    await btn('Desactivar conexión').click(); await idle();
    const disabled = await status();
    check(!disabled.enabled && disabled.discovery_state === 'disabled', 'disable-api-readback');
    await btn('Activar conexión').click(); await idle();
    await waitAnnounced();
    await btn('Actualizar estado').click(); await idle();
    check(await section.getAttribute('data-discovery-state') === 'announced', 'reenable-reannounces-without-manual-fields');
    await manual.locator('summary').click();
    check(await manual.locator('input[type=text]').inputValue() === (await status()).base_url, 'advanced-origin-from-backend');
    await btn('Regenerar clave…').click();
    const confirmation = page.getByRole('dialog', { name: '¿Regenerar la clave de conexión?', exact: true });
    check((await confirmation.innerText()).includes('sin copiar la clave'), 'automatic-rotation-explained');
    await confirmation.getByRole('button', { name: 'Regenerar clave', exact: true }).click(); await idle();
    check(rotations === 1 && tokenRequests === 0 && await manual.locator('input[type=password]').inputValue() === '', 'rotation-once-without-reveal');
    check((await manual.innerText()).includes('no necesitas copiar la clave'), 'automatic-rotation-no-copy-instruction');
    await waitAnnounced();
    await manual.locator('summary').click();
    await btn('Actualizar estado').click(); await idle();
    check(await section.locator('input:visible').count() === 0 && await section.getAttribute('data-discovery-state') === 'announced', 'post-rotation-normal-ui-announced-without-fields');
    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      await section.getByRole('heading').scrollIntoViewIfNeeded();
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `no-overflow-${width}`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await section.getByRole('heading').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, 'enlace-automatico-movil.png') });
    check(results.pageErrors === 0 && tokenRequests === 0, 'no-js-errors-or-key-fetches');
    results.passed = true;
  } finally {
    if (browser) await browser.close();
    fs.writeFileSync(path.join(out, 'enlace-automatico.json'), JSON.stringify(results, null, 2));
  }
  console.log(JSON.stringify(results, null, 2));
})().catch(error => { console.error('Fallo de prueba UI automática:', error.message); process.exitCode = 1; });
