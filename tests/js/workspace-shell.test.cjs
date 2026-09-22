// Dependency-free behavioral checks for the presentation-only shell.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const source = readFileSync(join(__dirname, '../../src/klen_clone/static/workspace-shell.js'), 'utf8');
const shell = readFileSync(join(__dirname, '../../src/klen_clone/static/erp.html'), 'utf8');
const styles = readFileSync(join(__dirname, '../../src/klen_clone/static/workspace-shell.css'), 'utf8');

function setup(stored = '{}', {mobile = false, grouped = false} = {}) {
  let document;
  class Element {
    constructor(text = '', tagName = 'DIV') {
      this.textContent = text; this.children = []; this.attributes = {}; this.dataset = {}; this.listeners = {}; this.value = ''; this.tagName = tagName;
      this.classes = new Set();
      this.classList = {toggle: (name, active) => active ? this.classes.add(name) : this.classes.delete(name)};
    }
    setAttribute(k, v) { this.attributes[k] = v; }
    removeAttribute(k) { delete this.attributes[k]; }
    addEventListener(k, v) { this.listeners[k] = v; }
    append(item) { item.parentElement = this; this.children = this.children.filter(child => child !== item); this.children.push(item); }
    prepend(item) { item.parentElement = this; this.children = this.children.filter(child => child !== item); this.children.unshift(item); }
    replaceChildren() { this.children = []; }
    closest() { return this.hidden ? this : null; }
    querySelector(selector) { return this.children.find(child => selector === 'button' ? child.tagName === 'BUTTON' : selector === 'small' ? child.tagName === 'SMALL' : false); }
    querySelectorAll() { return this.children; }
    matches(selector) { return selector === 'a[data-route]' && this.tagName === 'A' && Boolean(this.dataset.route); }
    focus() { document.activeElement = this; }
    click() { this.onclick?.(); }
    showModal() { this.open = true; }
    close() { this.open = false; this.listeners.close?.(); }
  }
  const selectors = ['#theme-toggle', '#density-toggle', '#motion-toggle', 'main > header', '.sidebar .brand', '#command-center', '#command-search', '#command-results', '#command-trigger', '#signed-in-user', '#breadcrumb-current'];
  const elements = Object.fromEntries(selectors.map(key => [key, new Element()]));
  elements['#nav'] = new Element();
  elements['#signed-in-user'].textContent = 'test-user';
  const links = ['overview', 'sales', 'reports', 'private'].map(route => {
    const link = new Element(route, 'A'); link.dataset.route = route; link.hash = '#' + route;
    link.childNodes = [{nodeType: 3, textContent: route}]; link.hidden = route === 'private'; return link;
  });
  const sections = [];
  if (grouped) {
    const makeSection = key => {
      const header = new Element('', 'P'); header.dataset.navSection = key;
      header.children = [new Element('', 'BUTTON'), new Element('', 'SMALL')];
      return header;
    };
    sections.push(makeSection('commercial'), makeSection('governance'));
    sections[0].nextElementSibling = links[1];
    links[1].nextElementSibling = sections[1];
    sections[1].nextElementSibling = links[2];
    links[2].nextElementSibling = links[3];
    links[3].nextElementSibling = null;
  }
  document = {documentElement: new Element(), activeElement: elements['#command-trigger'],
    querySelector: key => elements[key], querySelectorAll: selector => selector.includes('.nav-section') ? sections : links,
    createElement: () => new Element(), addEventListener() {}};
  let saved;
  const location = {hash: '#overview'};
  runInNewContext(source, {document, location, Node: {TEXT_NODE: 3},
    localStorage: {getItem: () => stored, setItem: (key, value) => { saved = {key, value: JSON.parse(value)}; }},
    matchMedia: query => ({matches: query.includes('max-width') ? mobile : false, addEventListener() {}}),
    MutationObserver: class {observe() {}}, addEventListener() {}});
  return {elements, links, sections, document, location, saved: () => saved};
}

test('malformed and non-object preferences do not break shell initialization', () => {
  for (const raw of ['broken json', 'null', '42', '"text"', '[]']) {
    const {document, saved} = setup(raw);
    assert.equal(document.documentElement.dataset.theme, 'light');
    assert.equal(saved().key, 'asas.workspace.v1:test-user');
  }
});

test('preferences are validated, persisted per user and described accessibly', () => {
  const {elements, document, saved} = setup('{"theme":"dark","density":"dense","collapsed":"false"}');
  assert.equal(document.documentElement.dataset.rail, 'expanded');
  assert.equal(document.documentElement.dataset.theme, 'dark');
  assert.match(elements['#density-toggle'].attributes['aria-label'], /dense/);
  assert.match(elements['#motion-toggle'].attributes['aria-label'], /smooth/);
  elements['#theme-toggle'].click();
  assert.equal(saved().value.theme, 'contrast');
  elements['#density-toggle'].click();
  assert.equal(saved().value.density, 'comfortable');
  elements['#motion-toggle'].click();
  assert.equal(document.documentElement.dataset.motion, 'reduced');
  assert.equal(saved().value.motion, 'reduced');
  assert.equal(elements['#motion-toggle'].attributes['aria-pressed'], 'true');
});

test('command results filter unavailable links, respect recency and navigate without transactions', () => {
  const {elements, location} = setup('{"recent":["reports","sales"]}');
  elements['#command-trigger'].click();
  const results = elements['#command-results'];
  assert.deepEqual(results.children.map(item => item.textContent), ['overview', 'reports', 'sales']);
  elements['#command-search'].value = 'sales';
  elements['#command-search'].oninput();
  assert.equal(results.children.length, 1);
  results.children[0].click();
  assert.equal(location.hash, '#sales');
  assert.equal(elements['#command-center'].open, false);
});

test('ArrowUp from search selects last result and closing restores focus', () => {
  const {elements, document} = setup();
  elements['#command-trigger'].click();
  const dialog = elements['#command-center'];
  dialog.listeners.keydown({key: 'ArrowUp', preventDefault() {}});
  assert.equal(document.activeElement.textContent, 'reports');
  dialog.close();
  assert.equal(document.activeElement, elements['#command-trigger']);
});

test('tablet navigation starts closed and toggles independently from desktop rail preference', () => {
  const {elements, document} = setup('{"collapsed":false}', {mobile: true});
  const root = document.documentElement;
  assert.equal(root.dataset.mobileNav, 'closed');
  assert.equal(elements['.sidebar .brand'].children[0].attributes['aria-expanded'], 'false');
  elements['.sidebar .brand'].children[0].click();
  assert.equal(root.dataset.mobileNav, 'open');
  assert.equal(root.dataset.rail, 'expanded');
  elements['.sidebar .brand'].children[0].click();
  assert.equal(root.dataset.mobileNav, 'closed');
});

test('enterprise navigation groups every route once under stable business domains', () => {
  const sections = [...shell.matchAll(/data-nav-section="([^"]+)"/g)].map(match => match[1]);
  const routes = [...shell.matchAll(/<a href="#[^"]+" data-route="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(sections, ['commercial', 'procurement', 'inventory', 'finance', 'organization', 'governance']);
  assert.equal(routes.length, 42);
  assert.equal(new Set(routes).size, routes.length);
  assert.equal(routes[0], 'overview');
  assert.equal(routes[1], 'my-workspace');
});

test('navigation uses one persisted accordion group without hiding routes from permissions or command search', () => {
  assert.match(source, /openGroup: typeof value\.openGroup === 'string'/);
  assert.match(source, /const collapsed = key !== preferences\.openGroup/);
  assert.match(source, /preferences\.openGroup = preferences\.openGroup === key \? null : key/);
  assert.match(source, /preferences\.openGroup = owner\?\.dataset\.navSection \|\| null/);
  assert.match(source, /classList\.toggle\('nav-group-collapsed', collapsed\)/);
  assert.match(source, /button\.setAttribute\('aria-expanded', String\(!collapsed\)\)/);
  assert.doesNotMatch(source, /preferences\.groups/);
  assert.match(styles, /#nav a\.nav-group-collapsed\{display:none\}/);
  assert.match(styles, /data-rail=collapsed.*#nav a\{display:none\}/);
  assert.match(styles, /data-rail=collapsed.*#nav a\.nav-priority.*#nav a\.active\{display:flex/);
  assert.match(styles, /nav-section\{display:block;grid-column:1\/-1/);
});

test('opening a navigation module closes every other module', () => {
  const {sections, links, saved} = setup('{}', {grouped: true});
  sections[0].querySelector('button').click();
  assert.equal(sections[0].attributes['data-collapsed'], undefined);
  assert.equal(sections[0].dataset.collapsed, 'false');
  assert.equal(sections[1].dataset.collapsed, 'true');
  assert.equal(links[1].classes.has('nav-group-collapsed'), false);
  assert.equal(links[2].classes.has('nav-group-collapsed'), true);
  sections[1].querySelector('button').click();
  assert.equal(sections[0].dataset.collapsed, 'true');
  assert.equal(sections[1].dataset.collapsed, 'false');
  assert.equal(links[1].classes.has('nav-group-collapsed'), true);
  assert.equal(links[2].classes.has('nav-group-collapsed'), false);
  assert.equal(saved().value.openGroup, 'governance');
});

test('shared motion system is smooth, restrained and respects reduced-motion preferences', () => {
  assert.match(styles, /--motion-slow:260ms/);
  assert.match(styles, /@keyframes workspace-enter/);
  assert.match(styles, /transition-behavior:allow-discrete/);
  assert.match(styles, /dialog\[open\]:not\(\.workspace-drawer\)/);
  assert.match(styles, /@media\(prefers-reduced-motion:reduce\)/);
  assert.match(styles, /:root\[data-motion=reduced\]/);
  assert.match(shell, /id="motion-toggle"/);
  assert.match(styles, /\.sidebar nav\{[^}]*align-content:start/);
  assert.match(styles, /\.sidebar nav:hover::-webkit-scrollbar-thumb/);
  assert.match(styles, /--glass-surface:/);
  assert.match(styles, /backdrop-filter:blur\(18px\) saturate\(1\.12\)/);
  assert.ok(styles.lastIndexOf('Keep the glass system authoritative') > styles.indexOf('Foundation v2'));
  assert.match(styles, /data-theme=contrast.*backdrop-filter:none!important/);
  assert.match(styles, /@media\(max-width:900px\).*backdrop-filter:blur\(8px\)/);
  assert.match(shell, /workspace-shell\.css\?v=20260922-login-motion-1/);
  assert.match(shell, /workspace-shell\.js\?v=20260922-login-motion-4/);
  assert.match(source, /URLSearchParams\(location\.search\)/);
  assert.match(source, /history\.replaceState/);
  assert.match(source, /workspace-entry-loader/);
  assert.match(source, /reduced \? 0 : 900/);
  assert.match(styles, /@keyframes workspace-arrival-progress/);
});
