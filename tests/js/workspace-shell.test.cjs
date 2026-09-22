// Dependency-free behavioral checks for the presentation-only shell.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const source = readFileSync(join(__dirname, '../../src/klen_clone/static/workspace-shell.js'), 'utf8');

function setup(stored = '{}', {mobile = false} = {}) {
  let document;
  class Element {
    constructor(text = '') { this.textContent = text; this.children = []; this.attributes = {}; this.dataset = {}; this.listeners = {}; this.value = ''; }
    setAttribute(k, v) { this.attributes[k] = v; }
    removeAttribute(k) { delete this.attributes[k]; }
    addEventListener(k, v) { this.listeners[k] = v; }
    append(item) { item.parentElement = this; this.children = this.children.filter(child => child !== item); this.children.push(item); }
    prepend(item) { item.parentElement = this; this.children = this.children.filter(child => child !== item); this.children.unshift(item); }
    replaceChildren() { this.children = []; }
    closest() { return this.hidden ? this : null; }
    querySelectorAll() { return this.children; }
    focus() { document.activeElement = this; }
    click() { this.onclick?.(); }
    showModal() { this.open = true; }
    close() { this.open = false; this.listeners.close?.(); }
  }
  const selectors = ['#theme-toggle', '#density-toggle', 'main > header', '.sidebar .brand', '#command-center', '#command-search', '#command-results', '#command-trigger', '#signed-in-user', '#breadcrumb-current'];
  const elements = Object.fromEntries(selectors.map(key => [key, new Element()]));
  elements['#signed-in-user'].textContent = 'test-user';
  const links = ['overview', 'sales', 'reports', 'private'].map(route => {
    const link = new Element(route); link.dataset.route = route; link.hash = '#' + route;
    link.childNodes = [{nodeType: 3, textContent: route}]; link.hidden = route === 'private'; return link;
  });
  document = {documentElement: new Element(), activeElement: elements['#command-trigger'],
    querySelector: key => elements[key], querySelectorAll: () => links,
    createElement: () => new Element(), addEventListener() {}};
  let saved;
  const location = {hash: '#overview'};
  runInNewContext(source, {document, location, Node: {TEXT_NODE: 3},
    localStorage: {getItem: () => stored, setItem: (key, value) => { saved = {key, value: JSON.parse(value)}; }},
    matchMedia: query => ({matches: query.includes('max-width') ? mobile : false, addEventListener() {}}),
    MutationObserver: class {observe() {}}, addEventListener() {}});
  return {elements, links, document, location, saved: () => saved};
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
  elements['#theme-toggle'].click();
  assert.equal(saved().value.theme, 'contrast');
  elements['#density-toggle'].click();
  assert.equal(saved().value.density, 'comfortable');
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
