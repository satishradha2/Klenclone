const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');

const root = join(__dirname, '../..');
const page = readFileSync(join(root, 'src/klen_clone/static/asas-login.html'), 'utf8');
const styles = readFileSync(join(root, 'src/klen_clone/static/asas-login.css'), 'utf8');
const behavior = readFileSync(join(root, 'src/klen_clone/static/asas-login.js'), 'utf8');

test('login is a responsive member of the centralized visual system', () => {
  assert.match(page, /Controlled staging/);
  assert.match(page, /Source protected/);
  assert.match(page, /Access scoped/);
  assert.match(page, /Posting locked/);
  assert.match(page, /id="login-form"/);
  assert.match(page, /autocomplete="username"/);
  assert.match(page, /autocomplete="current-password"/);
  assert.match(styles, /--nav:#15243b/);
  assert.match(styles, /--primary:#244f91/);
  assert.match(styles, /@media\(max-width:700px\)/);
  assert.match(styles, /@media\(max-width:430px\)/);
});

test('login presentation preserves the existing authentication contract', () => {
  assert.match(behavior, /fetch\('\/api\/v1\/auth\/login'/);
  assert.match(behavior, /username:form\.username\.value/);
  assert.match(behavior, /password:form\.password\.value/);
  assert.match(behavior, /location\.replace\('\/'\)/);
});
