// node tests/browser_v5_1.js URL DIRECTORIO_EVIDENCIAS (Playwright de npm ci).
// Servidor/SQLite reales temporales; sin interceptar ni simular respuestas API.
const { request } = require('playwright');
const { launchBrowser } = require('./browser_support');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [baseURL, out] = process.argv.slice(2);
assert.ok(baseURL && out);
fs.mkdirSync(out, { recursive: true });
const results = { realServer: true, mockedApi: false, realHomeAssistant: false, cases: [], errors: [], failedResponses: [] };
const record = name => results.cases.push({ name, status: 'passed' });
(async () => {
  const api = await request.newContext({ baseURL, extraHTTPHeaders: { 'X-Menu-Compra': '1' } });
  let browser;
  try {
    async function json(method, endpoint, data) {
      const response = await api.fetch(`/api/${endpoint}`, { method, ...(data === undefined ? {} : { data }) });
      assert.ok(response.ok(), `${method} ${endpoint}: ${response.status()} ${await response.text()}`);
      return response.json();
    }
    let bootstrap = await json('GET', 'bootstrap');
    assert.equal(bootstrap.version, '1.1.0');
    const category = bootstrap.categories.find(c => c.is_system);
    const store = bootstrap.supermarkets.find(s => s.is_system);
    const notes = 'Nota histórica conservada\nSegunda línea';
    const product = await json('POST', 'products', { name: 'Producto de prueba UI', category_id: category.id, supermarket_id: store.id, unit: 'ud', price_cents: 150, notes });
    await json('POST', 'shopping/quick-add', { name: product.name, product_id: product.id, quantity: 2 });
    const lines = data => data.groups.flatMap(group => group.items);
    const line = lines(await json('GET', 'shopping'))[0];
    await json('PATCH', `shopping/items/${line.id}`, { checked: true });
    browser = await launchBrowser();
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    page.on('pageerror', error => results.errors.push(error.message));
    page.on('response', response => {
      if (/\/(api|static)\//.test(response.url()) && response.status() >= 400) results.failedResponses.push({ url: response.url(), status: response.status() });
    });
    const dialog = () => page.locator('dialog[open]').last();
    const close = async () => { await dialog().getByRole('button', { name: 'Cerrar diálogo', exact: true }).click(); };
    const nav = async view => { await page.locator(`.main-nav [data-view="${view}"]`).click(); };
    await page.goto(baseURL);
    await page.waitForSelector('.day-card');
    await nav('shopping');
    await page.locator('.item-name').click();
    await dialog().getByLabel('Nombre del producto', { exact: true }).waitFor();
    assert.equal(await dialog().locator('textarea').count(), 0);
    assert.equal(await dialog().getByText('Notas (opcional)', { exact: true }).count(), 0);
    record('Nombre de compra abre editor sin campo ni etiqueta de notas');
    for (const label of ['Categoría', 'Supermercado']) {
      assert.equal(await dialog().getByLabel(label, { exact: true }).locator('option', { hasText: 'Sin especificar' }).count(), 1);
    }
    record('Opciones genéricas conservadas en ambos selectores del producto');
    await page.screenshot({ path: path.join(out, 'editor-compra-movil.png') });
    await dialog().getByLabel('Precio por unidad (€)', { exact: true }).fill('2,99');
    await dialog().getByRole('button', { name: 'Guardar cambios', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('dialog[open]'));
    await page.waitForFunction(() => document.querySelector('.item-meta')?.textContent.includes('2,99'));
    assert.equal((await json('GET', `products/${product.id}`)).notes, notes);
    const savedLine = lines(await json('GET', 'shopping'))[0];
    assert.equal(savedLine.unit_price_cents, 299);
    assert.equal(savedLine.quantity, 2);
    assert.equal(savedLine.checked, true);
    record('Guardar conserva notas antiguas, cantidad y comprado y sincroniza precio');
    await page.locator('.item-tools').getByRole('button', { name: `Editar ${product.name}`, exact: true }).click();
    await dialog().getByLabel('Nombre del producto', { exact: true }).waitFor();
    assert.equal(await dialog().locator('textarea').count(), 0);
    await dialog().getByRole('button', { name: 'Cancelar', exact: true }).click();
    assert.equal((await json('GET', `products/${product.id}`)).notes, notes);
    record('Botón Editar de compra tampoco muestra notas; cancelar conserva datos');
    await nav('products');
    await page.locator('.product-card').getByRole('button', { name: `Editar ${product.name}`, exact: true }).click();
    assert.equal(await dialog().getByLabel('Notas (opcional)', { exact: true }).inputValue(), notes);
    await dialog().getByRole('button', { name: '+ Crear categoría', exact: true }).click();
    assert.ok(await dialog().locator('.manager-item').count() > 0);
    assert.equal(await dialog().locator('.manager-list').getByText('Sin especificar', { exact: true }).count(), 0);
    await close();
    await dialog().getByRole('button', { name: '+ Crear supermercado', exact: true }).click();
    assert.equal(await dialog().locator('.manager-item').count(), 0);
    await dialog().getByText('Todavía no hay supermercados.', { exact: true }).waitFor();
    await close();
    await dialog().getByRole('button', { name: 'Cancelar', exact: true }).click();
    record('Gestores anidados ocultan reservas sin quitarlas del formulario ni del catálogo');
    await page.getByRole('button', { name: 'Categorías', exact: true }).click();
    assert.equal(await dialog().locator('.manager-item').count(), bootstrap.categories.filter(c => !c.is_system).length);
    assert.equal(await dialog().locator('.manager-list').getByText('Sin especificar', { exact: true }).count(), 0);
    await page.screenshot({ path: path.join(out, 'categorias-movil.png') });
    await close();
    record('Gestión de categorías muestra todas las ordinarias y oculta la reservada');
    // Probar lista vacía con datos reales: las categorías ordinarias no están usadas.
    for (const item of bootstrap.categories.filter(c => !c.is_system)) await json('DELETE', `categories/${item.id}`);
    await page.reload();
    await page.waitForSelector('.day-card');
    await page.locator('#settings-button').click();
    for (const [kind, title, emptyText] of [['categories', 'categorías', 'Todavía no hay categorías.'], ['supermarkets', 'supermercados', 'Todavía no hay supermercados.']]) {
      await dialog().getByRole('button', { name: `Gestionar ${title}`, exact: true }).click();
      assert.equal(await dialog().locator('.manager-item').count(), 0);
      await dialog().getByText(emptyText, { exact: true }).waitFor();
      assert.equal(await dialog().locator('.manager-list').getByText('Sin especificar', { exact: true }).count(), 0);
      record(`${title}: lista vacía correcta cuando solo existe la reserva`);
      const singular = kind === 'categories' ? 'categoría' : 'supermercado';
      const name = `Prueba ${singular}`;
      await dialog().getByLabel('Nombre', { exact: true }).fill(name);
      await dialog().getByRole('button', { name: `Crear ${singular}`, exact: true }).click();
      await dialog().locator('.manager-item strong', { hasText: name }).waitFor();
      assert.equal((await json('GET', kind)).filter(item => item.name === name).length, 1);
      await dialog().getByRole('button', { name: `Editar ${name}`, exact: true }).click();
      const renamed = `${name} editado`;
      await dialog().getByLabel('Nombre', { exact: true }).fill(renamed);
      await dialog().getByRole('button', { name: 'Guardar cambios', exact: true }).click();
      await dialog().locator('.manager-item strong', { hasText: renamed }).waitFor();
      assert.equal((await json('GET', kind)).filter(item => item.name === renamed).length, 1);
      await dialog().getByRole('button', { name: `Eliminar ${renamed}`, exact: true }).click();
      await dialog().getByRole('button', { name: 'Eliminar', exact: true }).click();
      await dialog().getByText(emptyText, { exact: true }).waitFor();
      const remaining = await json('GET', kind);
      assert.equal(remaining.length, 1);
      assert.equal(remaining[0].is_system, true);
      assert.equal(remaining[0].name, 'Sin especificar');
      record(`${title}: crear, editar y eliminar funciona y conserva la reserva oculta`);
      await close();
    }
    await close();
    bootstrap = await json('GET', 'bootstrap');
    assert.equal(bootstrap.uncategorized_count, 1);
    assert.equal(bootstrap.categories[0].id, category.id);
    assert.equal(bootstrap.supermarkets[0].id, store.id);
    await nav('products');
    assert.equal(await page.locator('#products-nav-count').textContent(), '1');
    assert.equal(await page.locator('#products-nav-count').isVisible(), true);
    for (const label of ['Filtrar por categoría', 'Filtrar por supermercado']) {
      assert.equal(await page.getByLabel(label, { exact: true }).locator('option', { hasText: 'Sin especificar' }).count(), 1);
    }
    record('Badge y filtros genéricos siguen funcionando tras gestionar metadatos');
    await page.setViewportSize({ width: 1280, height: 900 });
    await nav('shopping');
    await page.locator('.item-name').click();
    await dialog().getByLabel('Nombre del producto', { exact: true }).waitFor();
    assert.equal(await dialog().locator('textarea').count(), 0);
    await dialog().getByRole('button', { name: 'Cancelar', exact: true }).click();
    assert.equal((await json('GET', `products/${product.id}`)).notes, notes);
    record('Editor sin notas también en escritorio y datos finales conservados');
    assert.deepEqual(results.errors, []);
    assert.deepEqual(results.failedResponses, []);
    results.success = true;
  } finally {
    if (browser) await browser.close();
    await api.dispose();
    fs.writeFileSync(path.join(out, 'navegador.json'), JSON.stringify(results, null, 2));
  }
  console.log(JSON.stringify(results, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
