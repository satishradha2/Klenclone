/* Presentation preferences and deterministic navigation. No transaction calls. */
(() => {
  'use strict';
  const root = document.documentElement;
  const themes = ['system', 'light', 'dark', 'contrast'];
  const densities = ['comfortable', 'compact', 'dense'];
  const systemTheme = matchMedia('(prefers-color-scheme: dark)');
  const mobileViewport = matchMedia('(max-width: 900px)');
  let preferences = {}, storageKey = null;
  const read = () => {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || '{}');
      if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
      return {theme: value.theme, density: value.density, collapsed: value.collapsed === true,
        recent: Array.isArray(value.recent) ? value.recent.filter(key => typeof key === 'string').slice(0, 8) : []};
    } catch { return {}; }
  };
  const save = () => { if (storageKey) { try { localStorage.setItem(storageKey, JSON.stringify(preferences)); } catch { /* Storage may be disabled. */ } } };
  const themeButton = document.querySelector('#theme-toggle');
  const densityButton = document.querySelector('#density-toggle');
  function apply() {
    const theme = themes.includes(preferences.theme) ? preferences.theme : 'system';
    const density = densities.includes(preferences.density) ? preferences.density : 'comfortable';
    root.dataset.theme = theme === 'system' ? (systemTheme.matches ? 'dark' : 'light') : theme;
    root.dataset.density = density;
    root.dataset.rail = preferences.collapsed ? 'collapsed' : 'expanded';
    const toggleHost = mobileViewport.matches ? document.querySelector('.sidebar .brand') : document.querySelector('main > header');
    if (toggleHost && toggle.parentElement !== toggleHost) {
      if (mobileViewport.matches) toggleHost.append(toggle); else toggleHost.prepend(toggle);
    }
    themeButton.textContent = `Theme: ${theme}`;
    densityButton.textContent = `Density: ${density}`;
    themeButton.setAttribute('aria-label', `Change color theme, current: ${theme}`);
    densityButton.setAttribute('aria-label', `Change data density, current: ${density}`);
    const navigationOpen = mobileViewport.matches ? root.dataset.mobileNav === 'open' : !preferences.collapsed;
    toggle.setAttribute('aria-expanded', String(navigationOpen));
  }
  const toggle = document.createElement('button');
  toggle.type = 'button'; toggle.className = 'rail-toggle';
  toggle.textContent = '☰'; toggle.setAttribute('aria-label', 'Toggle navigation');
  toggle.setAttribute('aria-controls', 'nav');
  document.querySelector('main > header').prepend(toggle);
  toggle.onclick = () => {
    if (mobileViewport.matches) {
      root.dataset.mobileNav = root.dataset.mobileNav === 'open' ? 'closed' : 'open';
      apply();
      return;
    }
    preferences.collapsed = !preferences.collapsed; apply(); save();
  };
  themeButton.onclick = () => { preferences.theme = themes[(themes.indexOf(preferences.theme || 'system') + 1) % themes.length]; apply(); save(); };
  densityButton.onclick = () => { preferences.density = densities[(densities.indexOf(preferences.density || 'comfortable') + 1) % densities.length]; apply(); save(); };
  systemTheme.addEventListener('change', apply);
  mobileViewport.addEventListener('change', () => { root.dataset.mobileNav = 'closed'; apply(); });
  const links = [...document.querySelectorAll('#nav a[data-route]')];
  links.forEach(link => { link.title = [...link.childNodes].filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent).join('').trim(); link.setAttribute('aria-label', link.title); });
  const dialog = document.querySelector('#command-center');
  const input = document.querySelector('#command-search');
  const results = document.querySelector('#command-results');
  results.removeAttribute('role');
  let opener;
  function renderCommands() {
    const query = input.value.trim().toLocaleLowerCase();
    results.replaceChildren();
    const visible = links.filter(link => !link.hidden && !link.closest('[hidden]'));
    const recent = Array.isArray(preferences.recent) ? preferences.recent : [];
    const rank = link => { const index = recent.indexOf(link.dataset.route); return index < 0 ? Infinity : index; };
    visible.sort((a,b) => rank(a) - rank(b));
    visible.filter(link => link.title.toLocaleLowerCase().includes(query)).forEach(link => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'command-option';
      button.textContent = link.title;
      if (recent.includes(link.dataset.route)) { const hint = document.createElement('small'); hint.textContent = 'Recent'; button.append(hint); }
      button.onclick = () => { if (link.hidden) return; dialog.close(); location.hash = link.hash; };
      results.append(button);
    });
    if (!results.children.length) { const message = document.createElement('p'); message.textContent = 'No available pages match. Try another page name.'; results.append(message); }
  }
  function openCommands() { if (dialog.open) return; opener = document.activeElement; input.value = ''; renderCommands(); dialog.showModal(); input.focus(); }
  document.querySelector('#command-trigger').onclick = openCommands;
  input.oninput = renderCommands;
  dialog.addEventListener('close', () => opener?.focus());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('keydown', event => {
    const buttons = [...results.querySelectorAll('button')];
    const index = buttons.indexOf(document.activeElement);
    if (event.key === 'ArrowDown' && buttons.length) { event.preventDefault(); buttons[(index + 1) % buttons.length].focus(); }
    if (event.key === 'ArrowUp' && buttons.length) { event.preventDefault(); buttons[index < 0 ? buttons.length - 1 : (index - 1 + buttons.length) % buttons.length].focus(); }
    if (event.key === 'Enter' && document.activeElement === input) { event.preventDefault(); buttons[0]?.click(); }
  });
  document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openCommands(); } });
  function recordVisit() {
    const key = location.hash.slice(1).split('?')[0] || 'overview';
    const link = links.find(item => item.dataset.route === key && !item.hidden);
    const breadcrumb = document.querySelector('#breadcrumb-current');
    if (breadcrumb && link) breadcrumb.textContent = link.title;
    links.forEach(item => { if (item === link) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current'); });
    if (mobileViewport.matches) { root.dataset.mobileNav = 'closed'; apply(); }
    if (!storageKey || !link) return;
    preferences.recent = [key, ...(Array.isArray(preferences.recent) ? preferences.recent : []).filter(item => item !== key)].slice(0, 8); save();
  }
  // Bootstrap already authenticates the user. Observe its identity instead of
  // adding a duplicate session request or persisting ERP records in the browser.
  const identity = document.querySelector('#signed-in-user');
  function bindIdentity() { const user = identity.textContent.trim(); if (!user) return; const key = `asas.workspace.v1:${user}`; if (key !== storageKey) { storageKey = key; preferences = read(); apply(); recordVisit(); } }
  new MutationObserver(bindIdentity).observe(identity, {childList:true, subtree:true, characterData:true});
  addEventListener('hashchange', recordVisit);
  root.dataset.mobileNav = 'closed';
  apply(); bindIdentity();
})();
