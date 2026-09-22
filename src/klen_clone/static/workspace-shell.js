/* Presentation preferences and deterministic navigation. No transaction calls. */
(() => {
  'use strict';
  const root = document.documentElement;
  try {
    const arrivalRequested = new URLSearchParams(location.search).get('arrival') === '1';
    if (arrivalRequested) {
      history.replaceState(null, '', `${location.pathname}${location.hash}`);
      const arrival = document.createElement('div');
      arrival.className = 'workspace-entry-loader';
      arrival.setAttribute('role', 'status');
      arrival.setAttribute('aria-live', 'polite');
      arrival.innerHTML = '<span aria-hidden="true">A</span><p>Workspace ready<small>Controls and permissions loaded</small></p><i aria-hidden="true"></i>';
      document.body.append(arrival);
      root.dataset.workspaceArrival = 'active';
      addEventListener('load', () => {
        const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
        setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => {
          arrival.classList.add('is-complete');
          delete root.dataset.workspaceArrival;
          setTimeout(() => arrival.remove(), reduced ? 0 : 480);
        })), reduced ? 0 : 900);
      }, {once:true});
    }
  } catch { /* Session storage may be disabled. */ }
  const themes = ['system', 'light', 'dark', 'contrast'];
  const densities = ['comfortable', 'compact', 'dense'];
  const motions = ['smooth', 'reduced'];
  const systemTheme = matchMedia('(prefers-color-scheme: dark)');
  const mobileViewport = matchMedia('(max-width: 900px)');
  let preferences = {}, storageKey = null;
  const read = () => {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || '{}');
      if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
      return {theme: value.theme, density: value.density, motion: value.motion, collapsed: value.collapsed === true,
        recent: Array.isArray(value.recent) ? value.recent.filter(key => typeof key === 'string').slice(0, 8) : [],
        openGroup: typeof value.openGroup === 'string' ? value.openGroup : null};
    } catch { return {}; }
  };
  const save = () => { if (storageKey) { try { localStorage.setItem(storageKey, JSON.stringify(preferences)); } catch { /* Storage may be disabled. */ } } };
  const themeButton = document.querySelector('#theme-toggle');
  const densityButton = document.querySelector('#density-toggle');
  const motionButton = document.querySelector('#motion-toggle');
  function apply() {
    const theme = themes.includes(preferences.theme) ? preferences.theme : 'system';
    const density = densities.includes(preferences.density) ? preferences.density : 'comfortable';
    const motion = motions.includes(preferences.motion) ? preferences.motion : 'smooth';
    root.dataset.theme = theme === 'system' ? (systemTheme.matches ? 'dark' : 'light') : theme;
    root.dataset.density = density;
    root.dataset.motion = motion;
    root.dataset.rail = preferences.collapsed ? 'collapsed' : 'expanded';
    const toggleHost = mobileViewport.matches ? document.querySelector('.sidebar .brand') : document.querySelector('main > header');
    if (toggleHost && toggle.parentElement !== toggleHost) {
      if (mobileViewport.matches) toggleHost.append(toggle); else toggleHost.prepend(toggle);
    }
    themeButton.textContent = `Theme: ${theme}`;
    densityButton.textContent = `Density: ${density}`;
    motionButton.textContent = `Motion: ${motion}`;
    themeButton.setAttribute('aria-label', `Change color theme, current: ${theme}`);
    densityButton.setAttribute('aria-label', `Change data density, current: ${density}`);
    motionButton.setAttribute('aria-label', `Change interface motion, current: ${motion}`);
    motionButton.setAttribute('aria-pressed', String(motion === 'reduced'));
    const navigationOpen = mobileViewport.matches ? root.dataset.mobileNav === 'open' : !preferences.collapsed;
    toggle.setAttribute('aria-expanded', String(navigationOpen));
    applySections();
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
  motionButton.onclick = () => { preferences.motion = motions[(motions.indexOf(preferences.motion || 'smooth') + 1) % motions.length]; apply(); save(); };
  systemTheme.addEventListener('change', apply);
  mobileViewport.addEventListener('change', () => { root.dataset.mobileNav = 'closed'; apply(); });
  const links = [...document.querySelectorAll('#nav a[data-route]')];
  const sectionHeaders = [...document.querySelectorAll('#nav .nav-section[data-nav-section]')];
  links.forEach(link => { link.title = [...link.childNodes].filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent).join('').trim(); link.setAttribute('aria-label', link.title); });
  function sectionLinks(header) {
    const members = [];
    let sibling = header.nextElementSibling;
    while (sibling && sibling.tagName !== 'P') {
      if (sibling.matches?.('a[data-route]')) members.push(sibling);
      sibling = sibling.nextElementSibling;
    }
    return members;
  }
  function applySections() {
    if (!sectionHeaders.length) return;
    const availableKeys = sectionHeaders.map(header => header.dataset.navSection);
    if (!availableKeys.includes(preferences.openGroup)) preferences.openGroup = null;
    sectionHeaders.forEach(header => {
      const key = header.dataset.navSection;
      const members = sectionLinks(header);
      const visibleMembers = members.filter(link => !link.hidden);
      const collapsed = key !== preferences.openGroup;
      const button = header.querySelector('button');
      const count = header.querySelector('small');
      header.dataset.collapsed = String(collapsed);
      if (button) button.setAttribute('aria-expanded', String(!collapsed));
      if (count) {
        count.textContent = String(visibleMembers.length);
        count.setAttribute('aria-label', `${visibleMembers.length} available pages`);
      }
      members.forEach(link => link.classList.toggle('nav-group-collapsed', collapsed));
    });
  }
  sectionHeaders.forEach(header => {
    const button = header.querySelector('button');
    if (!button) return;
    button.onclick = () => {
      const key = header.dataset.navSection;
      preferences.openGroup = preferences.openGroup === key ? null : key;
      applySections();
      save();
    };
  });
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
    const owner = sectionHeaders.find(header => sectionLinks(header).includes(link));
    preferences.openGroup = owner?.dataset.navSection || null;
    applySections();
    if (mobileViewport.matches) { root.dataset.mobileNav = 'closed'; apply(); }
    if (!storageKey || !link) return;
    preferences.recent = [key, ...(Array.isArray(preferences.recent) ? preferences.recent : []).filter(item => item !== key)].slice(0, 8); save();
  }
  // Bootstrap already authenticates the user. Observe its identity instead of
  // adding a duplicate session request or persisting ERP records in the browser.
  const identity = document.querySelector('#signed-in-user');
  function bindIdentity() { const user = identity.textContent.trim(); if (!user) return; const key = `asas.workspace.v1:${user}`; if (key !== storageKey) { storageKey = key; preferences = read(); apply(); recordVisit(); } }
  new MutationObserver(bindIdentity).observe(identity, {childList:true, subtree:true, characterData:true});
  const navigation = document.querySelector('#nav');
  if (navigation) new MutationObserver(applySections).observe(navigation, {subtree:true, attributes:true, attributeFilter:['hidden']});
  addEventListener('hashchange', recordVisit);
  root.dataset.mobileNav = 'closed';
  apply(); bindIdentity();
})();
