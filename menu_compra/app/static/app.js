(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const main = $('#main-content');
  const moneyFormatter = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' });

  const dayFormatter = new Intl.DateTimeFormat('es-ES', { weekday: 'long' });
  const dateFormatter = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short' });
  const longDateFormatter = new Intl.DateTimeFormat('es-ES', { dateStyle: 'full' });
  let elementSequence = 0;
  let shoppingQueue = Promise.resolve();
  let weekRequest = 0;
  const pendingProductAdds = new Set();
  const pendingProductEditors = new Set();

  const composedParent = (node) => node.parentElement || node.getRootNode?.().host || null;

  // Coordinates stay local to this document. Ancestors are read, never changed.
  function visibleArea() {
    const height = window.innerHeight;
    const viewport = (win) => {
      const visual = win.visualViewport;
      return { top: visual?.offsetTop ?? 0, bottom: (visual?.offsetTop ?? 0) + (visual?.height ?? win.innerHeight) };
    };
    const own = viewport(window);
    let top = Math.max(0, own.top);
    let bottom = Math.min(height, own.bottom);
    let child = window;
    let origin = 0;
    let scale = 1;
    try {
      while (child !== child.parent) {
        const frame = child.frameElement;
        if (!frame) break; // Cross-origin embedding exposes no frameElement.
        const parent = child.parent;
        const rect = frame.getBoundingClientRect();
        const frameScale = frame.offsetHeight ? rect.height / frame.offsetHeight : 1;
        if (!(frameScale > 0)) break;
        origin = rect.top + frame.clientTop * frameScale + origin * frameScale;
        scale *= frameScale;
        const parentViewport = viewport(parent);
        top = Math.max(top, (parentViewport.top - origin) / scale);
        bottom = Math.min(bottom, (parentViewport.bottom - origin) / scale);
        for (let ancestor = composedParent(frame); ancestor; ancestor = composedParent(ancestor)) {
          const style = parent.getComputedStyle(ancestor);
          if (!/(auto|scroll|hidden|clip|overlay)/.test(`${style.overflowY} ${style.overflowX}`)) continue;
          const clip = ancestor.getBoundingClientRect();
          const clipScale = ancestor.offsetHeight ? clip.height / ancestor.offsetHeight : 1;
          const clipTop = clip.top + ancestor.clientTop * clipScale;
          top = Math.max(top, (clipTop - origin) / scale);
          bottom = Math.min(bottom, (clipTop + ancestor.clientHeight * clipScale - origin) / scale);
        }
        child = parent;
      }
    } catch (_) { /* Cross-origin parents: retain the readable/local viewport. */ }
    top = Math.min(height, Math.max(0, top));
    bottom = Math.max(top, Math.min(height, bottom));
    return { top, bottom, height: bottom - top, bottomInset: Math.max(0, height - bottom) };
  }
  function watchVisibleArea() {
    let queued = false;
    let stopped = false;
    const cleanup = [];
    const update = () => {
      queued = false;
      if (stopped) return;
      const area = visibleArea();
      const style = document.documentElement.style;
      style.setProperty('--visible-top', `${area.top}px`);
      style.setProperty('--visible-height', `${area.height}px`);
      style.setProperty('--bottom-inset', `${area.bottomInset}px`);
    };
    const schedule = () => {
      if (!stopped && !queued) { queued = true; window.requestAnimationFrame(update); }
    };
    const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null;
    let win = window;
    try {
      while (true) {
        const current = win;
        current.addEventListener('resize', schedule);
        current.addEventListener('orientationchange', schedule);
        current.addEventListener('scroll', schedule, { passive: true, capture: true });
        current.visualViewport?.addEventListener('resize', schedule);
        current.visualViewport?.addEventListener('scroll', schedule);
        cleanup.push(() => {
          current.removeEventListener('resize', schedule);
          current.removeEventListener('orientationchange', schedule);
          current.removeEventListener('scroll', schedule, true);
          current.visualViewport?.removeEventListener('resize', schedule);
          current.visualViewport?.removeEventListener('scroll', schedule);
        });
        if (win === win.parent || !win.frameElement) break;
        const frame = win.frameElement;
        for (let node = frame; node; node = composedParent(node)) {
          resize?.observe(node);
          // A banner sibling can resize (fonts/images) without any DOM mutation.
          for (let sibling = node.previousElementSibling; sibling; sibling = sibling.previousElementSibling) resize?.observe(sibling);
        }
        // Banner content/class changes can move a fixed-height iframe without resizing it.
        const observer = new MutationObserver(schedule);
        observer.observe(win.parent.document.documentElement, { attributes: true, childList: true, characterData: true, subtree: true });
        cleanup.push(() => observer.disconnect());
        win = win.parent;
      }
    } catch (_) { /* Parent access is optional, including sandboxed embeddings. */ }
    window.addEventListener('pagehide', () => {
      stopped = true;
      resize?.disconnect();
      cleanup.forEach((dispose) => dispose());
    }, { once: true });
    update();
  }

  function localISO(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }
  const today = () => localISO(new Date());
  const asDate = (iso) => new Date(`${iso}T12:00:00`);
  function shiftDate(iso, days) {
    const date = asDate(iso);
    date.setDate(date.getDate() + days);
    return localISO(date);
  }
  function monday(iso) {
    const date = asDate(iso);
    return shiftDate(iso, -((date.getDay() + 6) % 7));
  }
  const state = {
    view: 'menu', loading: true, ready: false, fatal: '',
    bootstrap: { categories: [], supermarkets: [], products: [] },
    shopping: null, menu: null, week: monday(today()), weekLoading: false, weekDuplicating: false, weekError: '',
    productQuery: '', categoryFilter: '', supermarketFilter: ''
  };

  // All remote and user-provided text goes through text nodes or DOM properties.
  function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    children.flat(Infinity).forEach((child) => {
      if (child !== null && child !== undefined && child !== false) {
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
      }
    });
    Object.entries(attributes).forEach(([key, value]) => {
      if (value === null || value === undefined) return;
      if (key.startsWith('on') && typeof value === 'function') {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === 'className' || key === 'class') {
        node.className = value;
      } else if (key === 'dataset') {
        Object.assign(node.dataset, value);
      } else if (['value', 'checked', 'disabled', 'required', 'readOnly', 'hidden', 'selected', 'multiple'].includes(key)) {
        node[key] = value;
      } else {
        node.setAttribute(key === 'htmlFor' ? 'for' : key, String(value));
      }
    });
    return node;
  }
  function button(label, handler, className = 'btn', attributes = {}) {
    const node = h('button', { type: 'button', className, ...attributes }, label);
    if (handler) node.addEventListener('click', async () => {
      if (node.disabled) return;
      node.disabled = true;
      try { await handler(); } catch (error) {
        const errorBox = node.closest('dialog')?.querySelector('.dialog-error');
        if (errorBox?.isConnected) {
          errorBox.textContent = error.message || 'No se ha podido completar la acción.';
          errorBox.hidden = false;
          errorBox.focus();
        } else toast(error.message || 'No se ha podido completar la acción.', true);
      }
      finally { if (node.isConnected) node.disabled = false; }
    });
    return node;
  }
  function field(label, control, hint = '') {
    if (!control.id) control.id = `field-${++elementSequence}`;
    const wrapper = h('div', { className: 'field' }, h('label', { htmlFor: control.id }, label), control);
    if (hint) {
      const id = `${control.id}-hint`;
      control.setAttribute('aria-describedby', id);
      wrapper.append(h('p', { id, className: 'hint' }, hint));
    }
    return wrapper;
  }
  const money = (cents) => Number.isFinite(Number(cents)) && cents !== null ? moneyFormatter.format(Number(cents) / 100) : '—';
  const quantityValue = (value) => String(value).replace('.', ',');
  const normalise = (text) => String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es');
  const sortedProducts = () => [...state.bootstrap.products].sort((a, b) => a.name.localeCompare(b.name, 'es') || a.supermarket_name.localeCompare(b.supermarket_name, 'es'));
  const productById = (id) => state.bootstrap.products.find((product) => product.id === Number(id));
  const productLabel = (product) => `${product.name} · ${product.supermarket_name} · ${money(product.price_cents)}/${product.unit}`;
  function parsePrice(value) {
    const text = String(value).trim();
    if (!/^\d+(?:[,.]\d{1,2})?$/.test(text)) throw new Error('Escribe un precio no negativo con un máximo de dos decimales, por ejemplo 1,50.');
    const parts = text.replace(',', '.').split('.');
    const cents = Number(parts[0]) * 100 + Number((parts[1] || '').padEnd(2, '0'));
    if (!Number.isSafeInteger(cents) || cents > 100000000) throw new Error('El precio no puede superar 1.000.000,00 €.');
    return cents;
  }
  function parseQuantity(value) {
    const text = String(value).trim().replace(',', '.');
    if (!/^\d+(?:\.\d{1,3})?$/.test(text)) throw new Error('Escribe una cantidad válida con un máximo de tres decimales, con coma o punto.');
    const number = Number(text);
    if (!Number.isFinite(number) || number <= 0 || number > 100000) throw new Error('La cantidad debe ser mayor que cero y no superar 100.000.');
    return number;
  }
  function priceInput(cents = 0) {
    return h('input', { type: 'text', inputmode: 'decimal', value: (Number(cents) / 100).toFixed(2).replace('.', ','), required: true, autocomplete: 'off', placeholder: '0,00' });
  }
  function quantityInput(value = 1) {
    return h('input', { type: 'text', inputmode: 'decimal', value: quantityValue(value), required: true, autocomplete: 'off' });
  }
  function selectOptions(select, items, placeholder, selected = '') {
    select.replaceChildren(h('option', { value: '' }, placeholder), ...items.map((item) => h('option', { value: item.id }, item.name)));
    select.value = String(selected ?? '');
  }
  function toast(message, error = false) {
    const notification = h('div', { className: `toast${error ? ' toast-error' : ''}` }, h('span', {}, message));
    notification.append(button('×', () => notification.remove(), '', { 'aria-label': 'Cerrar aviso' }));
    const activeDialog = [...document.querySelectorAll('dialog[open]')].at(-1);
    (activeDialog?.querySelector('.dialog-notifications') || $('#notifications')).append(notification);
    window.setTimeout(() => notification.remove(), error ? 12000 : 6500);
  }
  function errorText(detail) {
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((entry) => `${(entry.loc || []).filter((part) => part !== 'body').join(' · ')}: ${entry.msg || 'valor no válido'}`).join('. ');
    return 'No se ha podido completar la solicitud.';
  }
  async function api(path, options = {}) {
    const method = options.method || 'GET';
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 25000);
    const headers = { Accept: 'application/json' };
    if (method !== 'GET') headers['X-Menu-Compra'] = '1';
    const config = { method, headers, signal: controller.signal, credentials: 'same-origin', cache: 'no-store' };
    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      config.body = JSON.stringify(options.body);
    }
    try {
      const response = await fetch(`api/${path}`, config);
      const text = await response.text();
      let result = null;
      try { result = text ? JSON.parse(text) : null; } catch (_) {
        throw new Error(response.ok ? 'El servidor ha devuelto una respuesta no válida.' : `El servidor no está disponible (HTTP ${response.status}).`);
      }
      if (!response.ok) {
        const error = new Error(errorText(result?.detail) || `Error HTTP ${response.status}.`);
        error.status = response.status;
        error.data = result;
        throw error;
      }
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('El servidor tarda demasiado. Recarga los datos antes de repetir una operación: podría haberse guardado.');
      if (error instanceof TypeError) throw new Error('No se puede conectar con Menú y Compra. Comprueba la conexión y vuelve a intentarlo.');
      throw error;
    } finally { window.clearTimeout(timeout); }
  }

  function createDialog(title, { description = '', wide = false, form = false } = {}) {
    const id = `dialog-${++elementSequence}`;
    const dialog = h('dialog', { className: `modal${wide ? ' modal-wide' : ''}`, 'aria-labelledby': `${id}-title` });
    const closeButton = button('×', () => dialog.close(), 'modal-close', { 'aria-label': 'Cerrar diálogo' });
    const header = h('header', { className: 'modal-header' }, h('h2', { id: `${id}-title` }, title), closeButton);
    const error = h('div', { className: 'alert dialog-error', role: 'alert', hidden: true, tabindex: '-1' });
    const notifications = h('div', { className: 'dialog-notifications', role: 'status', 'aria-live': 'polite' });
    const content = h('div', { className: 'modal-content' });
    const body = h('div', { className: 'modal-body' });
    if (description) {
      body.append(h('p', { id: `${id}-description`, className: 'modal-description' }, description));
      dialog.setAttribute('aria-describedby', `${id}-description`);
    }
    body.append(notifications, error, content);
    const actions = h('div', { className: 'modal-actions' });
    const wrapper = h(form ? 'form' : 'div', {}, body, actions);
    dialog.append(header, wrapper);
    const previousFocus = document.activeElement;
    const disabledBefore = new Map();
    let busy = false;
    const result = {
      dialog, body: content, actions, form: form ? wrapper : null,
      close: () => dialog.close(),
      setError(message) {
        error.textContent = message || '';
        error.hidden = !message;
        if (message) error.focus();
      },
      setBusy(value) {
        busy = value;
        dialog.setAttribute('aria-busy', String(value));
        if (value) {
          dialog.querySelectorAll('button, input, select, textarea').forEach((control) => { disabledBefore.set(control, control.disabled); control.disabled = true; });
        } else {
          disabledBefore.forEach((wasDisabled, control) => { control.disabled = wasDisabled; });
          disabledBefore.clear();
        }
      }
    };
    dialog.addEventListener('cancel', (event) => { if (busy) event.preventDefault(); });
    dialog.addEventListener('close', () => {
      dialog.remove();
      if (previousFocus?.isConnected && !previousFocus.disabled) previousFocus.focus({ preventScroll: true });
    }, { once: true });
    document.body.append(dialog);
    dialog.showModal();
    return result;
  }
  function formActions(dialog, label, handler, leading = null) {
    if (leading) { leading.classList.add('action-leading'); dialog.actions.append(leading); }
    dialog.actions.append(button('Cancelar', () => dialog.close(), 'btn btn-quiet'), h('button', { type: 'submit', className: 'btn btn-primary' }, label));
    dialog.form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (dialog.dialog.getAttribute('aria-busy') === 'true') return;
      dialog.setError('');
      dialog.setBusy(true);
      try { await handler(); } catch (error) { if (dialog.dialog.isConnected) dialog.setError(error.message || 'No se ha podido guardar.'); else toast(error.message, true); }
      finally { dialog.setBusy(false); dialog.afterSubmit?.(); }
    });
  }
  function confirmDialog(title, message, label = 'Confirmar', danger = true) {
    return new Promise((resolve) => {
      const dialog = createDialog(title);
      let settled = false;
      dialog.body.append(h('p', { className: 'small' }, message));
      dialog.actions.append(button('Cancelar', () => { settled = true; resolve(false); dialog.close(); }, 'btn btn-quiet'), button(label, () => { settled = true; resolve(true); dialog.close(); }, `btn ${danger ? 'btn-danger' : 'btn-primary'}`));
      dialog.dialog.addEventListener('close', () => { if (!settled) resolve(false); }, { once: true });
      $('button', dialog.actions).focus();
    });
  }
  function emptyState(title, text, action = null, symbol = '✦') {
    return h('div', { className: 'empty-state' }, h('span', { className: 'empty-icon', 'aria-hidden': 'true' }, symbol), h('h3', {}, title), h('p', {}, text), action);
  }

  async function loadAll() {
    state.loading = true;
    state.fatal = '';
    render();
    try {
      const week = state.week;
      const [bootstrap, shopping, menu] = await Promise.all([api('bootstrap'), api('shopping'), api(`menu?week=${encodeURIComponent(week)}`)]);
      state.bootstrap = bootstrap;
      state.shopping = shopping;
      state.menu = menu;
      state.week = menu.week;
      state.weekError = '';
      state.ready = true;
    } catch (error) {
      state.fatal = error.message;
    } finally { state.loading = false; render(); }
  }
  // A successful write is not retried if its subsequent refresh fails.
  async function syncBootstrap(includeShopping = false) {
    const refresh = async () => {
      try {
        const [bootstrap, shopping] = await Promise.all([api('bootstrap'), includeShopping ? api('shopping') : Promise.resolve(null)]);
        state.bootstrap = bootstrap;
        if (includeShopping) state.shopping = shopping;
        if (!bootstrap.categories.some((item) => String(item.id) === state.categoryFilter)) state.categoryFilter = '';
        if (!bootstrap.supermarkets.some((item) => String(item.id) === state.supermarketFilter)) state.supermarketFilter = '';
        render();
        return true;
      } catch (error) {
        toast(`El cambio se ha guardado, pero no se ha podido actualizar ${includeShopping ? 'el catálogo y la lista' : 'el catálogo'}. ${error.message}`, true);
        return false;
      }
    };
    if (!includeShopping) return refresh();
    // Keep catalogue refreshes in the shopping queue, so an older row response
    // cannot overwrite the live price, unit, category or supermarket afterwards.
    const task = shoppingQueue.catch(() => {}).then(refresh);
    shoppingQueue = task;
    return task;
  }
  async function refreshMenu() {
    const requestedWeek = state.week;
    const request = ++weekRequest;
    state.weekLoading = true;
    state.weekError = '';
    render();
    try {
      const menu = await api(`menu?week=${encodeURIComponent(requestedWeek)}`);
      if (request === weekRequest) { state.menu = menu; state.week = menu.week; }
    } catch (error) {
      if (request === weekRequest) { state.menu = null; state.weekError = error.message; }
    } finally { if (request === weekRequest) { state.weekLoading = false; render(); } }
  }
  async function changeWeek(week) { state.week = week; state.menu = null; await refreshMenu(); }
  async function duplicateWeek() {
    if (state.weekLoading || state.weekDuplicating || !state.menu?.entries.length) return;
    const week = state.week;
    if (!await confirmDialog('¿Duplicar a la semana siguiente?', 'Se copiarán los platos a la semana siguiente. Se conservarán los de esta semana y todos los que ya haya en la siguiente, sin repetir los que ya estén. La lista de la compra no cambia.', 'Duplicar semana', false)) return;
    if (state.week !== week || state.weekLoading) throw new Error('La semana ha cambiado. Revisa la semana que quieres duplicar.');
    state.weekDuplicating = true;
    render();
    try {
      const result = await api('menu/duplicate-week', { method: 'POST', body: { week } });
      state.week = result.target_week;
      state.menu = null;
      await refreshMenu();
      const message = `${result.copied} ${result.copied === 1 ? 'plato copiado' : 'platos copiados'} · ${result.skipped} ya presentes. Se conserva el menú de destino.`;
      toast(state.weekError ? `${message} No se ha podido recargar la semana; pulsa «Reintentar».` : message, Boolean(state.weekError));
    } finally { state.weekDuplicating = false; render(); }
  }
  function mutateShopping(path, method, body) {
    const task = shoppingQueue.catch(() => {}).then(async () => {
      const shopping = await api(path, { method, body });
      state.shopping = shopping;
      render();
      return shopping;
    });
    shoppingQueue = task;
    return task;
  }
  function shoppingName(value) {
    const name = String(value).trim();
    if (!name) throw new Error('Escribe el nombre de un producto.');
    if ([...name].length > 180) throw new Error('El nombre para la compra puede tener como máximo 180 caracteres.');
    return name;
  }
  const findShoppingMatches = (name) => api(`products/matches?name=${encodeURIComponent(name)}`);
  function shoppingConflict(error) {
    return error.status === 409 && error.data?.status === 'choose' && error.data.matches?.length > 1 ? error.data : null;
  }
  function quickAddShopping(body) {
    const task = shoppingQueue.catch(() => {}).then(async () => {
      const result = await api('shopping/quick-add', { method: 'POST', body });
      state.shopping = result.shopping;
      state.bootstrap.products = [...state.bootstrap.products.filter((item) => item.id !== result.product.id), result.product];
      render();
      // A confirmed write must not become a retry just because a read fails.
      try { state.shopping = await api('shopping'); render(); }
      catch (error) { toast(`Producto añadido, pero no se ha podido recargar la lista. ${error.message}`, true); }
      await syncBootstrap();
      return result;
    });
    shoppingQueue = task;
    return task;
  }

  function productAddButton(product, className = 'btn btn-primary') {
    return button('+ A la lista', () => addProductToShopping(product), className, {
      disabled: pendingProductAdds.has(Number(product.id)),
      'aria-label': `Añadir ${product.name} a la compra`,
      dataset: { productAdd: product.id, focusKey: `product-add-${product.id}` }
    });
  }
  async function addProductToShopping(product) {
    const id = Number(product.id);
    if (pendingProductAdds.has(id)) return;
    const updateButtons = (disabled) => document.querySelectorAll('[data-product-add]').forEach((node) => {
      if (Number(node.dataset.productAdd) === id) node.disabled = disabled || node.closest('[aria-busy="true"]') !== null;
    });
    pendingProductAdds.add(id);
    updateButtons(true);
    try {
      // An explicit product ID pins this card's store; omitted price uses its live price.
      await quickAddShopping({ name: product.name, product_id: id, quantity: 1 });
      toast(`«${product.name}» añadido a la lista.`);
    } finally {
      pendingProductAdds.delete(id);
      updateButtons(false);
    }
  }
  async function editShoppingProduct(productId) {
    const id = Number(productId);
    if (pendingProductEditors.has(id)) return;
    pendingProductEditors.add(id);
    try { openProductEditor(await api(`products/${id}`), null, { showNotes: false }); }
    finally { pendingProductEditors.delete(id); }
  }

  function render() {
    const focus = document.activeElement;
    const focusKey = main.contains(focus) ? focus.dataset?.focusKey : null;
    const selection = focusKey && ['INPUT', 'TEXTAREA'].includes(focus.tagName) ? [focus.selectionStart, focus.selectionEnd] : null;
    const meta = {
      menu: ['Organiza la semana', 'Menú semanal', ''],
      shopping: ['', 'Lista de la compra', ''],
      products: ['Tu despensa, a tu manera', 'Productos', 'Tus productos, sus tiendas y sus precios.']
    }[state.view];
    $('#page-eyebrow').textContent = meta[0];
    $('#page-eyebrow').hidden = state.view === 'shopping';
    $('#page-title').textContent = meta[1];
    $('#page-description').textContent = meta[2];
    $('#page-description').hidden = state.view !== 'products';
    $('.app-footer').hidden = state.view === 'shopping';
    $('#app-version').textContent = `v${state.bootstrap.version || '1.0.0'}`;
    document.body.dataset.view = state.view;
    $('#shopping-fab').hidden = state.view !== 'shopping' || !state.ready || state.loading || Boolean(state.fatal);
    document.querySelectorAll('.main-nav [data-view]').forEach((node) => {
      if (node.dataset.view === state.view) node.setAttribute('aria-current', 'page');
      else node.removeAttribute('aria-current');
      node.disabled = state.loading;
    });
    const navCount = $('#shopping-nav-count');
    const pending = state.shopping ? state.shopping.count - state.shopping.checked_count : 0;
    navCount.hidden = !pending;
    navCount.textContent = String(pending);
    navCount.setAttribute('aria-label', `${pending} productos pendientes`);
    const genericCategory = state.bootstrap.categories.find((item) => item.is_system === true || item.name === 'Sin especificar');
    const uncategorized = genericCategory
      ? state.bootstrap.products.filter((product) => product.active !== false && Number(product.category_id) === Number(genericCategory.id)).length
      : state.bootstrap.uncategorized_count || 0;
    const productCount = $('#products-nav-count');
    productCount.hidden = !uncategorized;
    productCount.textContent = String(uncategorized);
    productCount.setAttribute('aria-label', `${uncategorized} productos sin especificar categoría`);
    $('.main-nav [data-view="products"]').setAttribute('aria-label', uncategorized ? `Productos: ${uncategorized} sin especificar categoría` : 'Productos');
    const actions = $('#page-actions');
    actions.replaceChildren();
    if (state.ready && !state.loading && !state.fatal) {
      if (state.view === 'shopping') actions.append(button('+ Añadir a la lista', () => openShoppingAdd(), 'btn btn-primary shopping-add-desktop'));
      else if (state.view === 'products') actions.append(button('+ Nuevo producto', () => openProductEditor(), 'btn btn-primary'));
    }
    main.setAttribute('aria-busy', String(state.loading));
    if (state.loading) {
      main.replaceChildren(h('div', { className: 'loading-state', role: 'status' }, h('span', { className: 'spinner', 'aria-hidden': 'true' }), h('p', {}, 'Cargando tus datos…')));
    } else if (state.fatal) {
      main.replaceChildren(emptyState('No hemos podido cargar tus datos', state.fatal, button('Volver a intentar', loadAll, 'btn btn-primary'), '!'));
    } else {
      main.replaceChildren(state.view === 'menu' ? renderMenu() : state.view === 'shopping' ? renderShopping() : renderProducts());
    }
    if (focusKey) {
      const replacement = [...main.querySelectorAll('[data-focus-key]')].find((node) => node.dataset.focusKey === focusKey);
      if (replacement) {
        replacement.focus({ preventScroll: true });
        if (selection && selection[0] !== null && typeof replacement.setSelectionRange === 'function') {
          try { replacement.setSelectionRange(...selection); } catch (_) { /* Some input types do not expose a selection. */ }
        }
      }
    }
  }

  function renderMenu() {
    const wrapper = h('div');
    const end = shiftDate(state.week, 6);
    const entries = state.menu?.entries || [];

    const navigation = h('div', { className: 'week-navigation' },
      button('‹', () => changeWeek(shiftDate(state.week, -7)), 'btn btn-icon', { disabled: state.weekDuplicating, 'aria-label': 'Semana anterior' }),
      h('div', { className: 'week-label', 'aria-live': 'polite' }, h('strong', {}, `${dateFormatter.format(asDate(state.week))} — ${dateFormatter.format(asDate(end))}`), h('small', {}, `De lunes a domingo · ${asDate(state.week).getFullYear()}${asDate(end).getFullYear() !== asDate(state.week).getFullYear() ? ` / ${asDate(end).getFullYear()}` : ''}`)),
      button('›', () => changeWeek(shiftDate(state.week, 7)), 'btn btn-icon', { disabled: state.weekDuplicating, 'aria-label': 'Semana siguiente' }),
      button('Hoy', () => changeWeek(monday(today())), 'btn btn-small', { disabled: state.weekDuplicating, 'aria-label': 'Ir a la semana actual' })
    );
    wrapper.append(h('div', { className: 'week-toolbar' },
      h('div', { className: 'week-controls' }, navigation, button(state.weekDuplicating ? 'Duplicando…' : 'Duplicar a la semana siguiente', duplicateWeek, 'btn btn-quiet btn-small', { disabled: !entries.length || state.weekLoading || state.weekDuplicating }))
    ));
    if (state.weekLoading) wrapper.append(h('div', { className: 'loading-state', role: 'status' }, h('span', { className: 'spinner', 'aria-hidden': 'true' }), 'Cargando la semana…'));
    else if (state.weekError) wrapper.append(emptyState('No se ha podido cargar esta semana', state.weekError, button('Reintentar', refreshMenu, 'btn btn-primary'), '!'));
    else {
      const grid = h('div', { className: 'week-grid' });
      for (let offset = 0; offset < 7; offset += 1) {
        const date = shiftDate(state.week, offset);
        const isToday = date === today();
        const card = h('article', { className: `day-card${isToday ? ' is-today' : ''}` });
        card.append(h('header', { className: 'day-header' }, h('h2', {}, dayFormatter.format(asDate(date))), h('span', { className: 'day-date' }, isToday ? `Hoy · ${dateFormatter.format(asDate(date))}` : dateFormatter.format(asDate(date)))));
        const meals = h('div', { className: 'meals' });
        for (const [slot, label, symbol] of [['lunch', 'Comida', '☀'], ['dinner', 'Cena', '☾']]) {
          const mealEntries = entries.filter((item) => item.date === date && item.slot === slot).sort((a, b) => (a.position || 0) - (b.position || 0) || a.id - b.id);
          const meal = h('section', { className: `meal meal-${slot}${mealEntries.length ? '' : ' is-empty'}`, 'aria-label': `${label} del ${longDateFormatter.format(asDate(date))}` }, h('h3', { className: 'meal-label' }, `${symbol} ${label}`));
          if (!mealEntries.length) {
            meal.tabIndex = 0;
            meal.setAttribute('aria-label', `Añadir plato a ${label.toLocaleLowerCase('es')} del ${longDateFormatter.format(asDate(date))}`);
            meal.addEventListener('click', (event) => {
              if (!event.target.closest('button, a, input, select, textarea')) openMenuEditor({ date, slot });
            });
            meal.addEventListener('keydown', (event) => {
              if (event.target === meal && ['Enter', ' '].includes(event.key)) {
                event.preventDefault();
                openMenuEditor({ date, slot });
              }
            });
          }
          const list = h('ul', { className: 'meal-dishes' });
          mealEntries.forEach((entry) => {
            list.append(h('li', { className: 'menu-dish' },
              button(entry.text, () => openMenuEditor({ date, slot, entry }), 'meal-name', { 'aria-label': `Editar plato ${entry.text}`, dataset: { focusKey: `menu-name-${entry.id}` } }),
              h('div', { className: 'menu-dish-tools' },
                button('Editar', () => openMenuEditor({ date, slot, entry }), 'text-button', { 'aria-label': `Editar plato ${entry.text}`, dataset: { focusKey: `menu-edit-${entry.id}` } }),
                button('Quitar', () => removeMenuEntry(entry), 'text-button remove', { 'aria-label': `Quitar plato ${entry.text}` })
              )
            ));
          });
          if (mealEntries.length) meal.append(list);
          else meal.append(h('p', { className: 'meal-placeholder' }, 'Sin platos todavía'));
          meal.append(button('+ Añadir plato', () => openMenuEditor({ date, slot }), 'text-button meal-add', { disabled: mealEntries.length >= 20, 'aria-label': `Añadir plato a ${label.toLocaleLowerCase('es')} del ${longDateFormatter.format(asDate(date))}`, dataset: { focusKey: `menu-${date}-${slot}` } }));
          if (mealEntries.length >= 20) meal.append(h('p', { className: 'hint' }, 'Máximo de 20 platos.'));
          meals.append(meal);
        }
        card.append(meals);
        grid.append(card);
      }
      wrapper.append(grid, h('p', { className: 'menu-footnote' }, 'Un plato por campo, tantos como necesites en cada comida o cena (máximo 20). Puedes añadirlo a la compra al crear o editar el plato.'));
    }
    return wrapper;
  }

  function renderProducts() {
    const wrapper = h('div');
    const search = h('input', { type: 'search', value: state.productQuery, placeholder: 'Buscar un producto…', 'aria-label': 'Buscar productos', dataset: { focusKey: 'product-search' }, onInput: (event) => { state.productQuery = event.target.value; render(); } });
    const category = h('select', { 'aria-label': 'Filtrar por categoría', dataset: { focusKey: 'category-filter' }, onChange: (event) => { state.categoryFilter = event.target.value; render(); } });
    const supermarket = h('select', { 'aria-label': 'Filtrar por supermercado', dataset: { focusKey: 'supermarket-filter' }, onChange: (event) => { state.supermarketFilter = event.target.value; render(); } });
    selectOptions(category, state.bootstrap.categories, 'Todas las categorías', state.categoryFilter);
    selectOptions(supermarket, state.bootstrap.supermarkets, 'Todas las tiendas', state.supermarketFilter);
    wrapper.append(h('div', { className: 'filter-bar' }, search, category, supermarket));
    const products = sortedProducts().filter((product) => normalise(`${product.name} ${product.notes || ''}`).includes(normalise(state.productQuery)) && (!state.categoryFilter || String(product.category_id) === state.categoryFilter) && (!state.supermarketFilter || String(product.supermarket_id) === state.supermarketFilter));
    wrapper.append(h('div', { className: 'filter-extras' }, h('p', { className: 'muted small', role: 'status' }, `${products.length} ${products.length === 1 ? 'producto' : 'productos'}`), h('div', { className: 'row' }, button('Categorías', () => openManager('categories'), 'text-button'), button('Supermercados', () => openManager('supermarkets'), 'text-button'))));
    if (!state.bootstrap.products.length) {
      wrapper.append(emptyState('Tu catálogo empieza aquí', 'Añade los productos que compras, su supermercado y su precio. Después podrás añadirlos a la lista, también desde el menú.', button('Añadir mi primer producto', () => openProductEditor(), 'btn btn-primary'), '▤'));
    } else if (!products.length) {
      wrapper.append(emptyState('No encontramos ese producto', 'Prueba con otro nombre o elimina los filtros.', button('Quitar filtros', () => { state.productQuery = ''; state.categoryFilter = ''; state.supermarketFilter = ''; render(); }, 'btn btn-secondary')));
    } else {
      const grid = h('div', { className: 'product-grid' });
      products.forEach((product) => grid.append(h('article', { className: 'product-card' },
        h('div', { className: 'product-card-top' }, h('div', {}, button(product.name, () => openProductDetail(product.id), 'product-title', { 'aria-label': `Ver detalles e historial de ${product.name}` }), h('p', { className: 'product-store' }, product.supermarket_name)), h('span', { className: 'pill' + (product.is_frozen ? ' pill-ice' : '') }, `${product.is_frozen ? '❄ ' : ''}${product.category_name}`)),
        h('p', { className: 'product-price' }, money(product.price_cents), h('small', {}, ` / ${product.unit}`)),
        product.notes ? h('p', { className: 'product-notes' }, product.notes) : null,
        h('div', { className: 'card-actions' }, productAddButton(product, 'btn btn-primary btn-small'), button('Editar', () => openProductEditor(product), 'btn btn-small', { 'aria-label': `Editar ${product.name}` }), button('Historial', () => openProductDetail(product.id), 'btn btn-quiet btn-small', { 'aria-label': `Historial de precios de ${product.name}` }))
      )));
      wrapper.append(grid);
    }
    return wrapper;
  }

  function renderShopping() {
    const shopping = state.shopping;
    if (!shopping) return emptyState('La lista no está disponible', 'Recarga los datos para volver a intentarlo.', button('Recargar', loadAll, 'btn btn-primary'), '!');
    const wrapper = h('div', { className: 'shopping-layout' });
    const list = h('div', { className: 'shopping-main' });
    list.append(h('p', { className: 'shopping-heading muted small', role: 'status' }, `${shopping.checked_count} de ${shopping.count} productos comprados`));
    if (!shopping.count) list.append(h('p', { className: 'muted small' }, 'La lista está vacía.'));
    // Respect the API order, including frozen categories at the end.
    shopping.groups.forEach((group) => {
      const section = h('section', { className: `shopping-group${group.is_frozen ? ' is-frozen' : ''}`, 'aria-label': group.name });
      section.append(h('header', { className: 'shopping-group-header' }, h('h2', {}, `${group.is_frozen ? '❄ ' : ''}${group.name}`), h('small', {}, group.is_frozen ? 'Para el final' : `${group.items.length} ${group.items.length === 1 ? 'producto' : 'productos'}`)));
      group.items.forEach((item) => {
        const checkbox = h('input', { type: 'checkbox', checked: item.checked, 'aria-label': `Marcar ${item.product_name} como ${item.checked ? 'pendiente' : 'comprado'}`, dataset: { focusKey: `check-${item.id}` } });
        checkbox.addEventListener('change', async () => {
          checkbox.disabled = true;
          try { await mutateShopping(`shopping/items/${item.id}`, 'PATCH', { checked: checkbox.checked }); }
          catch (error) { checkbox.checked = item.checked; checkbox.disabled = false; toast(error.message, true); }
        });
        const quantity = quantityInput(item.quantity);
        quantity.setAttribute('aria-label', `Cantidad de ${item.product_name}, en ${item.unit}`);
        quantity.dataset.focusKey = `quantity-${item.id}`;
        quantity.addEventListener('change', async () => {
          try {
            const value = parseQuantity(quantity.value);
            quantity.disabled = true;
            await mutateShopping(`shopping/items/${item.id}`, 'PATCH', { quantity: value });
          } catch (error) { quantity.value = quantityValue(item.quantity); quantity.disabled = false; toast(error.message, true); }
        });
        quantity.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') { event.preventDefault(); quantity.blur(); }
          else if (event.key === 'Escape') { quantity.value = quantityValue(item.quantity); quantity.blur(); }
        });
        const stepper = h('div', { className: 'quantity-stepper', role: 'group', 'aria-label': `Cantidad de ${item.product_name}, en ${item.unit}` },
          button('−', () => mutateShopping(`shopping/items/${item.id}/adjust`, 'POST', { delta: -1 }), 'btn quantity-step', { disabled: Number(item.quantity) <= 1, 'aria-label': `Restar 1 ${item.unit} de ${item.product_name}`, dataset: { focusKey: `decrease-${item.id}` } }),
          quantity,
          button('+', () => mutateShopping(`shopping/items/${item.id}/adjust`, 'POST', { delta: 1 }), 'btn quantity-step', { disabled: Number(item.quantity) + 1 > 100000, 'aria-label': `Sumar 1 ${item.unit} de ${item.product_name}`, dataset: { focusKey: `increase-${item.id}` } })
        );
        const info = h('div', { className: 'item-info' }, button(item.product_name, () => editShoppingProduct(item.product_id), 'item-name', { 'aria-label': `Editar ${item.product_name}`, dataset: { focusKey: `item-name-${item.id}` } }), h('p', { className: 'item-meta' }, `${item.supermarket_name} · ${money(item.unit_price_cents)} / ${item.unit}`),
          h('div', { className: 'item-tools' }, button('Editar', () => editShoppingProduct(item.product_id), 'text-button', { 'aria-label': `Editar ${item.product_name}`, dataset: { focusKey: `item-edit-${item.id}` } }), button('Quitar', () => removeShoppingItem(item), 'text-button remove', { 'aria-label': `Quitar ${item.product_name} de la lista` })));
        section.append(h('div', { className: `shopping-item${item.checked ? ' is-checked' : ''}` }, checkbox, info,
          h('div', { className: 'item-amount' }, h('div', { className: 'quantity-field' }, stepper, h('span', {}, item.unit)), h('span', { className: 'item-subtotal', 'aria-label': `Subtotal de ${item.product_name}: ${money(item.subtotal_cents)}` }, money(item.subtotal_cents)))
        ));
      });
      list.append(section);
    });
    wrapper.append(list);
    return wrapper;
  }

  function openManager(kind, onCreated = null) {
    const categories = kind === 'categories';
    const dialog = createDialog(categories ? 'Categorías' : 'Supermercados', { form: true, description: categories ? 'Organiza el recorrido. Las categorías de congelados siempre se mostrarán al final.' : 'Cada producto tiene su supermercado. Puedes guardar un mismo producto en tiendas diferentes.' });
    const list = h('div', { className: 'manager-list', 'aria-label': categories ? 'Categorías existentes' : 'Supermercados existentes' });
    const name = h('input', { type: 'text', required: true, maxlength: 180, autocomplete: 'off' });
    const heading = h('h3');
    dialog.body.append(list, heading, field('Nombre', name));
    const order = h('input', { type: 'number', min: 0, max: 10000, step: 1, value: 50, required: true });
    const frozen = h('input', { type: 'checkbox' });
    if (categories) dialog.body.append(field('Orden en la lista', order, 'Los números menores aparecen antes. Congelados se mantiene al final.'), h('label', { className: 'checkbox-label' }, frozen, 'Es una categoría de congelados'));
    let editing = null;
    const cancelEdit = button('Cancelar edición', () => { edit(null); name.focus(); }, 'btn btn-quiet', { hidden: true });
    function edit(item) {
      if (item?.is_system) return;
      editing = item;
      name.value = item?.name || '';
      order.value = item?.sort_order ?? 50;
      frozen.checked = Boolean(item?.is_frozen);
      heading.textContent = `${item ? 'Editar' : 'Añadir'} ${categories ? 'categoría' : 'supermercado'}`;
      $('button[type="submit"]', dialog.actions).textContent = item ? 'Guardar cambios' : categories ? 'Crear categoría' : 'Crear supermercado';
      cancelEdit.hidden = !item;
      dialog.setError('');
      drawList();
    }
    function drawList() {
      // Hide reserved rows only here; keep them in product selects, filters and data.
      const items = state.bootstrap[kind].filter((item) => !item.is_system && item.name !== 'Sin especificar');
      list.replaceChildren(...items.map((item) => h('div', { className: `manager-item${editing?.id === item.id ? ' is-editing' : ''}` },
        h('div', { className: 'manager-item-info' }, h('strong', {}, item.name), categories ? h('span', { className: 'muted small' }, `Orden ${item.sort_order}${item.is_frozen ? ' · ❄ Congelados' : ''}`) : null),
        h('div', { className: 'manager-item-actions' },
          button('Editar', () => { edit(item); name.focus(); }, 'text-button', { 'aria-label': `Editar ${item.name}` }),
          button('Eliminar', () => remove(item), 'text-button remove', { 'aria-label': `Eliminar ${item.name}` })
        )
      )));
      if (!items.length) list.append(h('p', { className: 'muted small' }, categories ? 'Todavía no hay categorías.' : 'Todavía no hay supermercados.'));
    }
    async function remove(item) {
      if (item.is_system) return;
      const message = categories
        ? `Se eliminará «${item.name}». Sus productos pasarán a «Sin especificar», sin borrar productos, menús ni historiales. La categoría genérica está protegida.`
        : `Se eliminará «${item.name}». Sus productos y líneas de compra pasarán a «Sin especificar». El historial conservará el nombre de la tienda eliminada. No se borran productos, menús ni historiales. Si quedan productos con el mismo nombre en «Sin especificar», se rechazará sin cambios. La tienda genérica está protegida.`;
      if (!await confirmDialog(categories ? '¿Eliminar esta categoría?' : '¿Eliminar este supermercado?', message, 'Eliminar')) return;
      dialog.setError('');
      dialog.setBusy(true);
      try {
        await api(`${kind}/${item.id}`, { method: 'DELETE' });
        state.bootstrap[kind] = state.bootstrap[kind].filter((entry) => entry.id !== item.id);
        await syncBootstrap(true);
        if (editing?.id === item.id) edit(null);
        else drawList();
        toast(categories ? 'Categoría eliminada. Sus productos se conservan.' : 'Supermercado eliminado. Sus productos e historial se conservan.');
      } finally { dialog.setBusy(false); }
    }
    formActions(dialog, categories ? 'Crear categoría' : 'Crear supermercado', async () => {
      if (editing?.is_system) throw new Error('La opción genérica está protegida.');
      const trimmedName = name.value.trim();
      if (!trimmedName) throw new Error('Escribe un nombre.');
      const body = { name: trimmedName };
      if (categories) {
        if (!order.value.trim() || !Number.isSafeInteger(Number(order.value)) || Number(order.value) < 0 || Number(order.value) > 10000) throw new Error('El orden debe ser un número entero entre 0 y 10.000.');
        body.sort_order = Number(order.value);
        body.is_frozen = frozen.checked;
      }
      const wasEditing = Boolean(editing);
      const saved = await api(editing ? `${kind}/${editing.id}` : kind, { method: editing ? 'PUT' : 'POST', body });
      state.bootstrap[kind] = [...state.bootstrap[kind].filter((item) => item.id !== saved.id), saved];
      await syncBootstrap(true);
      if (onCreated && !wasEditing) {
        dialog.close();
        onCreated(state.bootstrap[kind].find((item) => item.id === saved.id) || saved);
      } else edit(null);
      toast(wasEditing ? 'Cambios guardados.' : categories ? 'Categoría creada.' : 'Supermercado creado.');
    }, cancelEdit);
    edit(null);
    name.focus();
    return dialog;
  }

  function openProductEditor(product = null, onSaved = null, { initialName = '', submitLabel = '', notifySaved = true, showNotes = true } = {}) {
    const dialog = createDialog(product ? 'Editar producto' : 'Nuevo producto', { form: true, description: 'El precio corresponde a la unidad que indiques. Todos los importes se guardan en euros.', wide: true });
    const name = h('input', { type: 'text', required: true, maxlength: 180, value: product?.name || initialName, autocomplete: 'off' });
    const category = h('select', { required: true });
    const supermarket = h('select', { required: true });
    selectOptions(category, state.bootstrap.categories, 'Selecciona una categoría', product?.category_id);
    selectOptions(supermarket, state.bootstrap.supermarkets, 'Selecciona un supermercado', product?.supermarket_id || (state.bootstrap.supermarkets.length === 1 ? state.bootstrap.supermarkets[0].id : ''));
    const unitId = `units-${++elementSequence}`;
    const unit = h('input', { type: 'text', required: true, maxlength: 20, value: product?.unit || 'ud', list: unitId, autocomplete: 'off' });
    const units = h('datalist', { id: unitId }, ['ud', 'kg', 'g', 'l', 'ml', 'paquete', 'bote', 'docena'].map((value) => h('option', { value })));
    const price = priceInput(product?.price_cents ?? 0);
    const notes = showNotes ? h('textarea', { rows: 3, maxlength: 4000, value: product?.notes || '' }) : null;
    function manage(kind, select, placeholder) {
      const manager = openManager(kind, (created) => selectOptions(select, state.bootstrap[kind], placeholder, created.id));
      manager.dialog.addEventListener('close', () => {
        selectOptions(category, state.bootstrap.categories, 'Selecciona una categoría', category.value);
        selectOptions(supermarket, state.bootstrap.supermarkets, 'Selecciona un supermercado', supermarket.value);
      }, { once: true });
    }
    const categoryField = field('Categoría', category);
    categoryField.append(button('+ Crear categoría', () => manage('categories', category, 'Selecciona una categoría'), 'text-button'));
    const supermarketField = field('Supermercado', supermarket);
    supermarketField.append(button('+ Crear supermercado', () => manage('supermarkets', supermarket, 'Selecciona un supermercado'), 'text-button'));
    const nameField = field('Nombre del producto', name); nameField.classList.add('form-full');
    const notesField = notes ? field('Notas (opcional)', notes) : null;
    notesField?.classList.add('form-full');
    dialog.body.append(h('div', { className: 'form-grid' }, nameField, categoryField, supermarketField, field('Unidad de venta', unit, 'Por ejemplo: ud, kg o l.'), field('Precio por unidad (€)', price, 'Puedes ajustarlo antes de añadir el producto a la compra.'), notesField), units);
    const remove = product ? button('Eliminar producto', async () => {
      if (!await confirmDialog('¿Eliminar este producto definitivamente?', `Se eliminará «${product.name}» del catálogo, junto con sus líneas de compra, su historial de precios y sus referencias como ingrediente. Los textos del menú se conservan. Las copias de seguridad antiguas no se modifican.`, 'Eliminar producto')) return;
      dialog.setBusy(true);
      try {
        await api(`products/${product.id}`, { method: 'DELETE' });
        dialog.close();
        state.bootstrap.products = state.bootstrap.products.filter((item) => item.id !== product.id);
        await syncBootstrap(true);
        toast('Producto, líneas de compra e historial eliminados.');
      } finally { dialog.setBusy(false); }
    }, 'btn btn-danger btn-small') : null;
    formActions(dialog, submitLabel || (product ? 'Guardar cambios' : 'Crear producto'), async () => {
      const body = { name: name.value.trim(), category_id: Number(category.value), supermarket_id: Number(supermarket.value), unit: unit.value.trim(), notes: notes ? notes.value.trim() : product?.notes || '', price_cents: parsePrice(price.value) };
      if (!body.name || !body.unit) throw new Error('El nombre y la unidad no pueden estar vacíos.');
      if (!body.category_id || !body.supermarket_id) throw new Error('Selecciona categoría y supermercado.');
      const saved = await api(product ? `products/${product.id}` : 'products', { method: product ? 'PUT' : 'POST', body });
      dialog.close();
      // Publish the returned product before any refresh or callback can fail.
      // A failed shopping write must never leave a creation form to resubmit.
      const resolved = saved?.id ? saved : { ...product, ...body };
      if (resolved.id) {
        state.bootstrap.products = [...state.bootstrap.products.filter((item) => item.id !== resolved.id), resolved];
        render();
      }
      await syncBootstrap(true);
      if (notifySaved) toast(product ? 'Producto actualizado también en la lista de la compra.' : 'Producto creado.');
      if (onSaved && resolved.id) await onSaved(resolved);
    }, remove);
    name.focus();
    return dialog;
  }

  async function removeMenuEntry(entry) {
    if (!await confirmDialog('¿Quitar este plato?', `Se quitará «${entry.text}» del menú. Los demás platos y la lista de la compra no cambian.`, 'Quitar plato')) return false;
    await api(`menu/${entry.id}`, { method: 'DELETE' });
    await refreshMenu();
    toast('Plato retirado del menú.');
    return true;
  }

  function openMenuEditor({ entry = null, date = entry?.date || today(), slot = entry?.slot || 'lunch' } = {}) {
    const existing = $('dialog[data-menu-editor]');
    if (existing) { $('input', existing)?.focus(); return; }
    const dialog = createDialog(entry ? 'Editar plato' : 'Añadir platos al menú', { form: true, wide: true, description: entry ? 'Solo se modificará este plato. Los demás se conservan.' : 'Escribe un plato por campo. Puedes añadir varios a la misma comida o cena, sin sustituir los que ya hay.' });
    dialog.dialog.dataset.menuEditor = 'true';
    const dateInput = h('input', { type: 'date', required: true, value: date });
    const slotInput = h('select', { required: true }, h('option', { value: 'lunch' }, 'Comida'), h('option', { value: 'dinner' }, 'Cena'));
    slotInput.value = slot;
    function createDraft(value = '') {
      const input = h('input', { type: 'text', required: true, maxlength: entry ? 500 : 180, value, autocomplete: 'off', placeholder: 'Por ejemplo: Filetes de cerdo' });
      const feedback = h('p', { className: 'hint menu-shopping-feedback', role: 'status', hidden: true });
      const action = h('button', { type: 'button', className: 'text-button menu-draft-shopping', disabled: !value.trim() }, 'Añadir a la compra');
      const draft = { input, feedback, action };
      input.addEventListener('input', () => { action.disabled = !input.value.trim(); feedback.hidden = true; });
      action.addEventListener('click', () => addDraftToShopping(draft));
      return draft;
    }
    const drafts = [createDraft(entry?.text || '')];
    const list = h('div', { className: 'menu-draft-list' });
    const add = h('button', { type: 'button', className: 'btn btn-secondary', onClick: () => {
      if (drafts.length >= 20) return;
      const draft = createDraft();
      drafts.push(draft);
      drawDrafts();
      draft.input.focus();
    } }, '+ Otro plato');
    function refreshDraftActions() {
      drafts.forEach((draft) => { draft.action.disabled = !draft.input.value.trim(); });
    }
    async function addDraftToShopping(draft) {
      if (dialog.dialog.getAttribute('aria-busy') === 'true' || !draft.input.value.trim()) return;
      dialog.setError('');
      dialog.setBusy(true);
      draft.feedback.hidden = false;
      draft.feedback.textContent = 'Añadiendo a la compra…';
      let name;
      const added = (result) => {
        draft.feedback.textContent = `«${result.product.name}» añadido a la compra. El menú aún no se ha guardado.`;
        draft.feedback.hidden = false;
      };
      const choose = (matches) => {
        draft.feedback.textContent = 'Elige el producto y supermercado para añadirlo.';
        openShoppingAdd(null, { initialName: name, initialMatches: matches, lockName: true, onAdded: added });
      };
      try {
        name = shoppingName(draft.input.value);
        const matches = await findShoppingMatches(name);
        if (matches.status === 'choose') choose(matches);
        else if (['unique', 'missing'].includes(matches.status)) added(await quickAddShopping({ name, quantity: 1 }));
        else throw new Error('No se han podido resolver las coincidencias. Vuelve a intentarlo.');
      } catch (error) {
        const conflict = shoppingConflict(error);
        if (conflict) choose(conflict);
        else { draft.feedback.textContent = error.message; dialog.setError(error.message); }
      } finally { dialog.setBusy(false); refreshDraftActions(); }
    }
    function drawDrafts() {
      list.replaceChildren(...drafts.map((draft, index) => {
        const nameField = field(entry ? 'Nombre del plato' : `Plato ${index + 1}`, draft.input);
        nameField.append(draft.action, draft.feedback);
        return h('div', { className: 'menu-draft-row' }, nameField,
          !entry && drafts.length > 1 ? button('×', () => { drafts.splice(index, 1); drawDrafts(); drafts[Math.min(index, drafts.length - 1)].input.focus(); }, 'btn btn-quiet btn-icon', { 'aria-label': `Quitar campo de plato ${index + 1}` }) : null
        );
      }));
      add.disabled = drafts.length >= 20;
    }
    drawDrafts();
    dialog.body.append(h('div', { className: 'form-grid' }, field('Fecha', dateInput), field('Momento del día', slotInput)), list);
    if (!entry) dialog.body.append(add, h('p', { className: 'hint' }, 'Máximo 20 platos por comida o cena, contando los ya guardados. No se separan los nombres automáticamente.'));
    const remove = entry ? button('Quitar este plato', async () => { if (await removeMenuEntry(entry)) dialog.close(); }, 'btn btn-danger btn-small') : null;
    formActions(dialog, entry ? 'Guardar plato' : 'Guardar en el menú', async () => {
      const texts = drafts.map((draft) => draft.input.value.trim());
      if (texts.some((text) => !text)) throw new Error('Escribe un nombre en cada campo o quita los campos vacíos.');
      if (!entry && texts.some((text) => [...text].length > 180)) throw new Error('Cada plato puede tener como máximo 180 caracteres.');
      const body = { date: dateInput.value, slot: slotInput.value };
      if (!body.date) throw new Error('Selecciona una fecha.');
      if (entry) await api(`menu/${entry.id}`, { method: 'PUT', body: { ...body, text: texts[0], dish_id: null } });
      else await api('menu/batch', { method: 'POST', body: { ...body, texts } });
      dialog.close();
      state.week = monday(body.date);
      state.menu = null;
      await refreshMenu();
      toast(`${texts.length === 1 ? 'Plato guardado' : `${texts.length} platos guardados`}.`);
    }, remove);
    dialog.afterSubmit = refreshDraftActions;
    drafts[0].input.focus();
    return dialog;
  }

  function openShoppingAdd(initialProductId = null, { initialName = '', initialMatches = null, lockName = false, onAdded = null } = {}) {
    const initialProduct = initialProductId ? productById(initialProductId) : null;
    const dialog = createDialog(lockName ? 'Elegir producto para la compra' : 'Añadir a la compra', { form: true });
    const search = h('input', { type: 'search', required: true, maxlength: 180, value: initialProduct?.name || initialName, placeholder: 'Escribe el nombre del producto…', autocomplete: 'off' });
    const product = h('select');
    const productField = field('Producto y supermercado', product);
    const quantity = quantityInput(1);
    quantity.required = false;
    const price = priceInput();
    price.required = false;
    price.value = '';
    const status = h('p', { className: 'hint', role: 'status', 'aria-live': 'polite' });
    let resolution = null;
    let resolvedName = '';
    let explicitId = null;
    let lookupSequence = 0;
    let timer = null;
    let pending = null;
    const selectedProduct = () => resolution?.status === 'unique' ? resolution.matches[0] : resolution?.matches.find((item) => item.id === explicitId);
    function refreshControls() {
      const busy = dialog.dialog.getAttribute('aria-busy') === 'true';
      const choose = resolution?.status === 'choose';
      const selected = selectedProduct();
      productField.hidden = !choose;
      product.required = choose;
      product.disabled = busy || !choose;
      price.disabled = busy || !selected;
      price.placeholder = selected ? (selected.price_cents / 100).toFixed(2).replace('.', ',') : '0,00';
    }
    function showSelection() {
      const selected = selectedProduct();
      if (resolution?.status === 'missing') {
        price.value = '';
        status.textContent = 'Se creará con precio 0 € · ud · categoría y supermercado Sin especificar.';
      } else if (selected) {
        status.textContent = `${productLabel(selected)}. Cantidad en ${selected.unit}.`;
      } else if (resolution?.status === 'choose') {
        status.textContent = 'Hay varias coincidencias. Elige el producto y supermercado.';
      } else status.textContent = search.value.trim() ? 'Buscando coincidencias…' : 'Escribe un nombre para añadirlo a la lista.';
      refreshControls();
    }
    function applyResolution(result, name, chosenId = null) {
      resolution = result;
      resolvedName = name;
      explicitId = chosenId;
      product.replaceChildren(h('option', { value: '' }, 'Selecciona producto y supermercado'), ...(result.status === 'choose' ? result.matches.map((item) => h('option', { value: item.id }, productLabel(item))) : []));
      product.value = '';
      showSelection();
    }
    async function resolveNow() {
      window.clearTimeout(timer);
      const name = shoppingName(search.value);
      if (resolution && resolvedName === name) return resolution;
      if (pending?.name === name) return pending.promise;
      const request = ++lookupSequence;
      const promise = (async () => {
        try {
          const result = await findShoppingMatches(name);
          if (!['unique', 'choose', 'missing'].includes(result.status)) throw new Error('No se han podido resolver las coincidencias.');
          if (request === lookupSequence && dialog.dialog.isConnected) applyResolution(result, name);
          return result;
        } catch (error) {
          if (request === lookupSequence && dialog.dialog.isConnected) status.textContent = error.message;
          throw error;
        } finally { if (request === lookupSequence) pending = null; }
      })();
      pending = { name, promise };
      return promise;
    }
    search.addEventListener('input', () => {
      window.clearTimeout(timer);
      lookupSequence += 1;
      pending = null;
      resolution = null;
      resolvedName = '';
      explicitId = null;
      price.value = '';
      dialog.setError('');
      showSelection();
      if (search.value.trim()) timer = window.setTimeout(() => resolveNow().catch(() => {}), 250);
    });
    product.addEventListener('change', () => {
      explicitId = Number(product.value) || null;
      price.value = '';
      showSelection();
    });
    const adjustments = h('div', { className: 'form-grid' }, field('Cantidad (opcional)', quantity, 'Por defecto, 1 unidad de venta.'), field('Precio por unidad (€), opcional', price, 'Vacío: precio actual. Cambiarlo actualiza el catálogo y su historial.'));
    dialog.body.append(lockName ? h('p', { className: 'small' }, `«${search.value}»`) : field('Nombre del producto', search), productField, status,
      lockName ? h('details', { className: 'menu-shopping-options' }, h('summary', {}, 'Ajustar cantidad o precio (opcional)'), adjustments) : adjustments);
    formActions(dialog, 'Añadir a la lista', async () => {
      const name = shoppingName(search.value);
      // Flush the debounce and await any lookup already in flight.
      const matches = await resolveNow();
      if (matches.status === 'choose' && !selectedProduct()) throw new Error('Selecciona el producto y supermercado que quieres añadir.');
      const body = { name, quantity: quantity.value.trim() ? parseQuantity(quantity.value) : 1 };
      // Only an explicit choice pins an ID; a unique lookup is rechecked atomically by the server.
      if (explicitId) body.product_id = explicitId;
      if (matches.status !== 'missing' && price.value.trim()) body.price_cents = parsePrice(price.value);
      let result;
      try { result = await quickAddShopping(body); }
      catch (error) {
        const conflict = shoppingConflict(error);
        if (!conflict) throw error;
        price.value = '';
        applyResolution(conflict, name);
        dialog.setError(error.message);
        return;
      }
      dialog.close();
      if (onAdded) onAdded(result);
      else toast(result.created ? 'Producto creado con precio 0 € y añadido a la lista.' : 'Producto añadido a la lista.');
    });
    dialog.afterSubmit = refreshControls;
    dialog.dialog.addEventListener('close', () => { window.clearTimeout(timer); lookupSequence += 1; }, { once: true });
    if (initialProduct) applyResolution({ status: 'unique', matches: [initialProduct] }, search.value.trim(), initialProduct.id);
    else if (initialMatches) applyResolution(initialMatches, search.value.trim());
    else {
      showSelection();
      if (search.value.trim()) resolveNow().catch(() => {});
    }
    (lockName ? product : initialProduct ? quantity : search).focus();
    return dialog;
  }

  async function removeShoppingItem(item) {
    if (!await confirmDialog('¿Quitar este producto?', `Se quitará «${item.product_name}» de la lista de la compra. El producto seguirá en el catálogo.`, 'Quitar de la lista')) return;
    await mutateShopping(`shopping/items/${item.id}`, 'DELETE');
    toast('Producto retirado de la lista.');
  }
  async function clearChecked() {
    if (!state.shopping?.checked_count) return;
    if (!await confirmDialog('¿Limpiar los productos comprados?', `Se quitarán ${state.shopping.checked_count} productos marcados como comprados. Los pendientes se conservan.`, 'Limpiar comprados')) return;
    await mutateShopping('shopping/checked', 'DELETE');
    toast('Productos comprados eliminados de la lista.');
    return true;
  }
  async function clearShopping() {
    if (!state.shopping?.count) return;
    if (!await confirmDialog('¿Limpiar toda la lista de la compra?', 'Se quitarán todos los productos de la lista, comprados y pendientes. El catálogo, el historial de precios y los menús se conservan. Esta acción no se puede deshacer.', 'Limpiar todos')) return;
    await mutateShopping('shopping', 'DELETE');
    toast('Lista vaciada. El catálogo, el historial y los menús se conservan.');
    return true;
  }

  function readableTimestamp(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value || 'Fecha no disponible') : new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }
  const historyStore = (entry) => `${entry.supermarket_name || 'Sin especificar'}${entry.supermarket_deleted ? ' (eliminado)' : ''}`;
  function svgElement(tag, attributes = {}, text = null) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== null) node.textContent = text;
    return node;
  }
  function priceChart(history) {
    const entries = [...history].reverse().filter((entry) => Number.isFinite(Number(entry.price_cents)));
    if (!entries.length) return null;
    const prices = entries.map((entry) => Number(entry.price_cents));
    const low = Math.min(...prices);
    const high = Math.max(...prices);
    const range = high - low;
    const titleId = `price-chart-${++elementSequence}`;
    const svg = svgElement('svg', { viewBox: '0 0 640 220', class: 'price-chart', role: 'img', 'aria-labelledby': `${titleId} ${titleId}-description` });
    svg.append(svgElement('title', { id: titleId }, 'Evolución del precio por unidad'), svgElement('desc', { id: `${titleId}-description` }, `${entries.length} registros, del más antiguo al más reciente. Precio mínimo ${money(low)} y máximo ${money(high)}. El detalle de cada registro está en la tabla siguiente.`));
    const x = (index) => entries.length === 1 ? 350 : 93 + (index / (entries.length - 1)) * 517;
    const y = (price) => range ? 169 - ((price - low) / range) * 136 : 101;
    const levels = range ? [[high, 33], [low, 169]] : [[low, 101]];
    levels.forEach(([price, position]) => {
      svg.append(svgElement('line', { x1: 88, y1: position, x2: 615, y2: position, stroke: '#dce3d1', 'stroke-dasharray': '4 5' }), svgElement('text', { x: 12, y: position + 4 }, money(price)));
    });
    if (entries.length > 1) svg.append(svgElement('polyline', { points: entries.map((entry, index) => `${x(index)},${y(entry.price_cents)}`).join(' '), fill: 'none', stroke: '#355848', 'stroke-width': 2.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    entries.forEach((entry, index) => {
      const point = svgElement('circle', { cx: x(index), cy: y(entry.price_cents), r: 4, fill: '#fffefa', stroke: '#355848', 'stroke-width': 2 });
      point.append(svgElement('title', {}, `${readableTimestamp(entry.recorded_at)}: ${money(entry.price_cents)} · ${historyStore(entry)}`));
      svg.append(point);
    });
    const label = (entry) => {
      const date = new Date(entry.recorded_at);
      return Number.isNaN(date.getTime()) ? '' : dateFormatter.format(date);
    };
    svg.append(svgElement('text', { x: 93, y: 204 }, label(entries[0])), svgElement('text', { x: 610, y: 204, 'text-anchor': 'end' }, label(entries[entries.length - 1])));
    return svg;
  }
  async function openProductDetail(productId) {
    const dialog = createDialog('Producto e historial', { wide: true });
    dialog.actions.append(button('Cerrar', () => dialog.close(), 'btn'));
    const loading = () => h('div', { className: 'loading-state', role: 'status' }, h('span', { className: 'spinner', 'aria-hidden': 'true' }), 'Cargando historial…');
    dialog.body.append(loading());
    async function load() {
      try {
        const product = await api(`products/${productId}`);
        if (dialog.dialog.isConnected) draw(product);
      } catch (error) {
        if (!dialog.dialog.isConnected) return;
        dialog.body.replaceChildren(h('div', { className: 'alert' }, error.message), button('Reintentar', load, 'btn btn-secondary'));
      }
    }
    function draw(product) {
      dialog.setError('');
      const history = product.price_history || [];
      const description = h('div', {}, h('h3', {}, product.name), h('p', { className: 'muted small' }, `${product.supermarket_name} · ${product.category_name}`));
      const price = priceInput(product.price_cents);
      const updateError = h('p', { className: 'alert', role: 'alert', hidden: true });
      const updateButton = h('button', { type: 'submit', className: 'btn btn-secondary' }, 'Actualizar precio');
      const form = h('form', { className: 'price-update-form' }, field(`Precio por ${product.unit} (€)`, price), updateButton);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (updateButton.disabled) return;
        updateError.hidden = true;
        let written = false;
        try {
          const cents = parsePrice(price.value);
          dialog.setBusy(true);
          await api(`products/${product.id}/price`, { method: 'POST', body: { price_cents: cents } });
          written = true;
          await syncBootstrap(true);
          const fresh = await api(`products/${product.id}`);
          if (dialog.dialog.isConnected) draw(fresh);
          toast('Precio actualizado también en la lista de la compra.');
        } catch (error) {
          if (dialog.dialog.isConnected) {
            updateError.textContent = written ? `El precio se ha guardado, pero no se ha podido recargar el historial. ${error.message}` : error.message;
            updateError.hidden = false;
          }
        } finally { dialog.setBusy(false); }
      });
      const historySection = h('section', {}, h('h3', {}, 'Historial de precios'), h('p', { className: 'hint' }, 'Los nombres se actualizan al renombrar una tienda. Si se elimina, los registros anteriores conservan su nombre con la indicación «eliminado».'));
      if (history.length) {
        const chart = priceChart(history);
        if (chart) historySection.append(chart);
        const sources = { initial: 'Alta', manual: 'Manual', shopping: 'Compra', update: 'Catálogo', product: 'Catálogo', restore: 'Restauración' };
        historySection.append(h('div', { className: 'history-scroll', tabindex: '0', role: 'region', 'aria-label': 'Tabla del historial de precios' }, h('table', { className: 'history-table' }, h('caption', { className: 'sr-only' }, `Historial de ${product.name}, del más reciente al más antiguo`), h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Fecha'), h('th', { scope: 'col' }, 'Supermercado / origen'), h('th', { scope: 'col' }, 'Precio'))), h('tbody', {}, history.map((entry) => h('tr', {}, h('td', {}, readableTimestamp(entry.recorded_at)), h('td', {}, historyStore(entry), h('div', { className: 'muted' }, sources[entry.source] || entry.source || '')), h('td', {}, money(entry.price_cents))))))));
      } else historySection.append(h('p', { className: 'info-box' }, 'Este producto todavía no tiene registros de precio.'));
      dialog.body.replaceChildren(description, h('div', { className: 'product-detail-price' }, h('strong', {}, `${money(product.price_cents)} / ${product.unit}`), h('span', { className: `pill${product.is_frozen ? ' pill-ice' : ''}` }, product.category_name)), product.notes ? h('p', { className: 'product-detail-note' }, product.notes) : h('span', { hidden: true }), form, updateError, historySection);
      dialog.actions.replaceChildren(button('Editar producto', () => { dialog.close(); openProductEditor(product); }, 'btn btn-secondary'), productAddButton(product), button('Cerrar', () => dialog.close(), 'btn btn-quiet'));
    }
    await load();
  }

  function haConnectionSection(settings) {
    const section = h('section', { className: 'settings-section ha-connection', 'aria-labelledby': 'ha-connection-title' },
      h('h3', { id: 'ha-connection-title' }, 'Conectar con Home Assistant'),
      h('p', {}, 'Permite que la integración de Menú y Compra acceda al menú y a la compra. Está desactivado inicialmente. Usa una clave propia, no la de Home Assistant ni la de Telegram.')
    );
    const status = h('p', { role: 'status', 'aria-live': 'polite' }, 'Consultando conexión…');
    const errorBox = h('div', { className: 'alert', role: 'alert', hidden: true, tabindex: '-1' });
    const url = h('input', { type: 'text', readOnly: true, value: '', autocomplete: 'off' });
    const key = h('input', { type: 'password', readOnly: true, value: '', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'none' });
    const keyField = field('Clave de conexión', key, 'Se mantiene oculta y solo se carga cuando pulsas «Mostrar clave». No se guarda en este navegador.');
    keyField.hidden = true;
    const feedback = h('p', { className: 'hint', role: 'status', 'aria-live': 'polite' });
    let connection = null;
    let busy = false;
    let generation = 0;
    let copiedByEvent = false;
    const active = () => settings.dialog.isConnected && settings.dialog.open;
    const controls = [];
    function clearKey() {
      generation += 1; // Ignore any response that arrives after hiding/closing.
      key.value = '';
      keyField.hidden = true;
      feedback.textContent = '';
    }
    function draw() {
      const enabled = connection?.enabled === true;
      status.textContent = busy ? 'Consultando conexión…' : connection ? enabled ? 'Conexión activada.' : 'Conexión desactivada. Las llamadas de la integración están bloqueadas.' : 'No se ha podido consultar la conexión.';
      toggle.textContent = enabled ? 'Desactivar conexión' : 'Activar conexión';
      toggle.className = `btn ${enabled ? 'btn-danger' : 'btn-primary'}`;
      toggle.disabled = busy || !connection;
      show.textContent = key.value ? 'Ocultar clave' : 'Mostrar clave';
      show.disabled = busy || !enabled || !connection?.has_token;
      copy.disabled = busy || !enabled || !key.value;
      rotate.disabled = busy || !enabled;
      reload.disabled = busy;
      if (!enabled) clearKey();
      controls.forEach((control) => { control.setAttribute('aria-disabled', String(control.disabled)); });
      section.setAttribute('aria-busy', String(busy));
    }
    function acceptStatus(result) {
      if (typeof result?.enabled !== 'boolean' || typeof result.has_token !== 'boolean' || typeof result.base_url !== 'string' || result.protocol_version !== 1) {
        throw new Error('invalid-status');
      }
      connection = result;
      url.value = result.base_url;
      if (!result.enabled || !result.has_token) clearKey();
    }
    async function run(action, failure) {
      if (busy || !active()) return;
      busy = true;
      errorBox.hidden = true;
      errorBox.textContent = '';
      draw();
      try { await action(); }
      catch (_) {
        // Never render response bodies from secret endpoints, even on failure.
        if (active()) {
          errorBox.textContent = failure;
          errorBox.hidden = false;
          errorBox.focus();
        }
      } finally { busy = false; if (active()) draw(); }
    }
    function control(label, handler, className = 'btn') {
      const node = h('button', { type: 'button', className, onClick: handler }, label);
      controls.push(node);
      return node;
    }
    async function refresh() {
      try {
        const result = await api('ha/status');
        if (active()) acceptStatus(result);
      } catch (error) {
        if (active()) { connection = null; clearKey(); }
        throw error;
      }
    }
    const toggle = control('Activar conexión', () => run(async () => {
      const enabled = !connection.enabled;
      clearKey();
      try {
        const result = await api('ha/config', { method: 'POST', body: { enabled } });
        if (!active()) return;
        acceptStatus(result);
        await refresh();
        if (active() && connection.enabled !== enabled) throw new Error('status-mismatch');
      } catch (error) {
        // A timed-out write may have completed: require a fresh status, not a retry.
        connection = null;
        throw error;
      }
    }, 'No se ha podido confirmar el cambio. Pulsa «Actualizar estado» antes de volver a intentarlo.'));
    const show = control('Mostrar clave', () => run(async () => {
      if (key.value) { clearKey(); return; }
      const request = generation;
      const result = await api('ha/token', { method: 'POST', body: {} });
      if (!active() || request !== generation || !connection?.enabled) return;
      if (typeof result?.token !== 'string' || !result.token) throw new Error('invalid-token');
      key.value = result.token;
      keyField.hidden = false;
    }, 'No se ha podido cargar la clave. Actualiza el estado y vuelve a intentarlo.'));
    // The copy event also supports Ctrl+C / long-press without a plaintext field.
    function copyKeyEvent(event) {
      if (!active() || !connection?.enabled || !key.value || !event.clipboardData) return;
      event.clipboardData.setData('text/plain', key.value);
      event.preventDefault();
      copiedByEvent = true;
    }
    key.addEventListener('copy', copyKeyEvent);
    const copy = control('Copiar clave', () => run(async () => {
      const request = generation;
      feedback.textContent = '';
      try {
        if (!navigator.clipboard?.writeText) throw new Error('clipboard-unavailable');
        await navigator.clipboard.writeText(key.value);
        if (active() && request === generation) feedback.textContent = 'Clave copiada. Pégala en la integración de Menú y Compra y no la compartas.';
        return;
      } catch (_) { /* HTTP Ingress may not provide the Clipboard API. */ }
      if (!active() || request !== generation || !key.value) return;
      copiedByEvent = false;
      let copied = false;
      // Browsers may suppress copy events on password fields. Select a harmless
      // space instead and supply the secret only through the clipboard event.
      const copyAnchor = h('textarea', { readOnly: true, value: ' ', className: 'sr-only', tabindex: '-1', 'aria-hidden': 'true' });
      section.append(copyAnchor);
      document.addEventListener('copy', copyKeyEvent, true);
      try {
        copyAnchor.focus();
        copyAnchor.select();
        copied = document.execCommand('copy') && copiedByEvent;
      } catch (_) { /* Manual copy below. */ }
      finally {
        document.removeEventListener('copy', copyKeyEvent, true);
        copyAnchor.remove();
        key.focus();
        key.select();
      }
      feedback.textContent = copied ? 'Clave copiada. Pégala en la integración de Menú y Compra y no la compartas.' : 'La copia automática está bloqueada. La clave está seleccionada: pulsa Ctrl+C (⌘C en Mac) o usa Copiar. Si el navegador lo impide, abre Home Assistant mediante HTTPS y vuelve a pulsar «Copiar clave».';
    }, 'No se ha podido copiar la clave. Selecciona el campo y usa Copiar o Ctrl+C.'));
    const rotate = control('Regenerar clave…', () => run(async () => {
      clearKey();
      if (!await confirmDialog('¿Regenerar la clave de conexión?', 'La clave anterior dejará de funcionar inmediatamente. Tendrás que actualizar la clave en la integración de Menú y Compra de Home Assistant. No se modifican el menú, la compra ni el catálogo.', 'Regenerar clave')) return;
      if (!active()) return;
      // Rotation is not a reveal request. Discard the returned secret.
      await api('ha/rotate', { method: 'POST', body: {} });
      if (!active()) return;
      await refresh();
      if (active()) feedback.textContent = 'Clave regenerada. Pulsa «Mostrar clave» y «Copiar clave», y actualízala en la integración de Home Assistant. La anterior ya no funciona.';
    }, 'No se ha podido confirmar la regeneración. No se reintentará automáticamente. Actualiza el estado y consulta la clave antes de cambiarla en la integración.'), 'btn btn-danger');
    const reload = control('Actualizar estado', () => run(async () => { clearKey(); await refresh(); }, 'No se ha podido consultar la conexión. El resto de ajustes sigue disponible. Comprueba la conexión y pulsa «Actualizar estado».'), 'btn btn-quiet');
    section.append(status, errorBox, field('URL interna para la integración', url, 'Accesible desde Home Assistant; no es la dirección de Ingress ni una URL pública.'),
      h('div', { className: 'row ha-connection-actions' }, toggle, reload),
      h('div', { className: 'row ha-connection-actions' }, show, copy, rotate), keyField, feedback,
      h('p', { className: 'hint' }, 'Desactivar bloquea el acceso sin borrar tus datos. Las copias JSON no incluyen esta clave. Configura Telegram y los chats permitidos en la integración de Home Assistant.')
    );
    settings.dialog.addEventListener('close', clearKey, { once: true });
    settings.dialog.addEventListener('cancel', clearKey);
    const onPageHide = () => { clearKey(); draw(); };
    window.addEventListener('pagehide', onPageHide);
    settings.dialog.addEventListener('close', () => window.removeEventListener('pagehide', onPageHide), { once: true });
    draw();
    run(refresh, 'No se ha podido consultar la conexión. El resto de ajustes sigue disponible. Comprueba la conexión y pulsa «Actualizar estado».');
    return section;
  }

  function openSettings() {
    const dialog = createDialog('Datos y ajustes', { description: 'Tus datos se guardan en esta instalación de Home Assistant. Las copias se descargan directamente, sin servicios externos.' });
    const copy = h('section', { className: 'settings-section' }, h('h3', {}, 'Copia de seguridad'), h('p', {}, 'Incluye menú, productos, tiendas, categorías, historial de precios y lista de la compra. También conserva los datos antiguos.'), h('a', { className: 'btn btn-secondary', href: 'api/backup', download: 'menu-compra-copia.json' }, '↓ Descargar copia JSON'));
    const file = h('input', { type: 'file', accept: '.json,application/json' });
    const restore = h('section', { className: 'settings-section' }, h('h3', {}, 'Restaurar una copia'), h('p', {}, 'La restauración reemplaza todos los datos actuales. Descarga antes una copia si quieres conservarlos.'), field('Archivo de copia JSON', file));
    const restoreButton = button('Restaurar copia…', async () => {
      dialog.setError('');
      const selected = file.files?.[0];
      if (!selected) { dialog.setError('Selecciona un archivo de copia JSON.'); return; }
      if (selected.size > 64 * 1024 * 1024) { dialog.setError('La copia supera el límite de 64 MiB. Utiliza una copia de seguridad de Home Assistant.'); return; }
      let backup;
      try { backup = JSON.parse(await selected.text()); }
      catch (_) { dialog.setError('No se puede leer este archivo como JSON. Selecciona una copia de Menú y Compra.'); return; }
      if (backup?.format !== 'menu-compra' || ![1, 2, 3].includes(backup?.version) || !backup?.tables || typeof backup.tables !== 'object' || Array.isArray(backup.tables)) {
        dialog.setError('El archivo no tiene el formato de copia de Menú y Compra, versión 1, 2 o 3.'); return;
      }
      if (!await confirmDialog('¿Reemplazar todos los datos?', `Se restaurará «${selected.name}». Se sustituirán el menú, el catálogo, los precios, la lista y los datos antiguos. Esta operación no se puede deshacer sin otra copia.`, 'Sí, reemplazar todo')) return;
      dialog.setBusy(true);
      try {
        await shoppingQueue.catch(() => {});
        await api('restore', { method: 'POST', body: backup });
        dialog.close();
        state.productQuery = ''; state.categoryFilter = ''; state.supermarketFilter = '';
        await loadAll();
        toast(state.fatal ? 'Copia restaurada. No se han podido recargar los datos; pulsa «Volver a intentar».' : 'Copia restaurada y datos actualizados.', Boolean(state.fatal));
      } catch (error) { dialog.setError(error.message); }
      finally { dialog.setBusy(false); }
    }, 'btn btn-danger');
    restore.append(restoreButton);
    const shoppingTools = h('section', { className: 'settings-section' }, h('h3', {}, 'Lista de la compra'), h('div', { className: 'row' },
      h('a', { className: 'btn btn-secondary', href: 'api/shopping/export', download: 'lista-compra.txt' }, '↓ Exportar lista'),
      button('Limpiar comprados', async () => { if (await clearChecked()) dialog.close(); }, 'btn btn-quiet', { disabled: !state.shopping?.checked_count }),
      button('Limpiar todos', async () => { if (await clearShopping()) dialog.close(); }, 'btn btn-danger', { disabled: !state.shopping?.count })
    ));
    const metadata = h('section', { className: 'settings-section' }, h('h3', {}, 'Categorías y supermercados'), h('p', {}, 'Crea, edita o elimina categorías y tiendas. Los cambios se reflejan en el catálogo y en la lista de la compra.'), h('div', { className: 'row' },
      button('Gestionar categorías', () => openManager('categories'), 'btn btn-secondary'),
      button('Gestionar supermercados', () => openManager('supermarkets'), 'btn btn-secondary')
    ));
    dialog.body.append(shoppingTools, metadata, haConnectionSection(dialog), copy, restore, h('section', { className: 'settings-section' }, h('h3', {}, 'Actualizar los datos'), h('p', {}, 'Vuelve a cargar el menú, el catálogo y la lista desde tu instalación.'), button('Recargar datos', async () => { dialog.close(); await loadAll(); }, 'btn')));
    dialog.actions.append(button('Cerrar', () => dialog.close(), 'btn btn-quiet'));
  }

  document.querySelectorAll('.main-nav [data-view]').forEach((node) => node.addEventListener('click', () => {
    state.view = node.dataset.view;
    render();
    main.focus({ preventScroll: true });
  }));
  $('#settings-button').addEventListener('click', openSettings);
  $('#shopping-fab').addEventListener('click', () => openShoppingAdd());
  window.addEventListener('pageshow', (event) => { if (event.persisted) watchVisibleArea(); });
  watchVisibleArea();
  loadAll();
})();
