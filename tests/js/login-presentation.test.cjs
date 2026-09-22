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
  assert.match(styles, /@media\(min-width:921px\)/);
  assert.match(styles, /grid-template-columns:minmax\(520px,46%\)/);
  assert.match(styles, /input:-webkit-autofill/);
});

test('login presentation preserves the existing authentication contract', () => {
  assert.match(behavior, /fetch\('\/api\/v1\/auth\/login'/);
  assert.match(behavior, /username:form\.username\.value/);
  assert.match(behavior, /password:form\.password\.value/);
  assert.match(behavior, /location\.replace\('\/\?arrival=1'\)/);
});

test('login motion is polished and honors reduced-motion preferences', () => {
  assert.match(styles, /@keyframes login-rise/);
  assert.match(styles, /@keyframes login-drift/);
  assert.match(styles, /@media\(prefers-reduced-motion:reduce\)/);
  assert.match(page, /id="login-transition"/);
  assert.match(page, /asas-login\.css\?v=20260922-login-motion-1/);
  assert.match(page, /asas-login\.js\?v=20260922-login-motion-2/);
  assert.match(styles, /@keyframes transition-orbit/);
  assert.match(styles, /@keyframes transition-progress/);
  assert.match(styles, /@keyframes button-spin/);
  assert.match(behavior, /data\.detail\|\|'Sign-in failed'/);
  assert.match(behavior, /location\.replace\('\/\?arrival=1'\)/);
  assert.doesNotMatch(behavior, /existing\(\)/);
  assert.match(behavior, /if\(submitting\)return/);
  assert.match(behavior, /form\.password\.focus\(\)/);
});

test('login surfaces use a restrained glass treatment', () => {
  assert.match(styles, /\.auth-wrap form\{background:rgba\(255,255,255,.9\)/);
  assert.match(styles, /backdrop-filter:blur\(20px\) saturate\(1\.08\)/);
  assert.match(styles, /\.environment\{background:rgba\(255,255,255,.09\)/);
});
