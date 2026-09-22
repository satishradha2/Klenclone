/* Read-only record inspection and permission-filtered attention surfaces. */
(() => {
  'use strict';
  const content = document.querySelector('#content');
  const attentionTrigger = document.querySelector('#attention-trigger');
  const attentionCount = document.querySelector('#attention-count');
  const attentionDialog = document.querySelector('#attention-center');
  const attentionSummary = document.querySelector('#attention-summary');
  const attentionItems = document.querySelector('#attention-items');
  const inspector = document.querySelector('#record-inspector');
  const inspectorTitle = document.querySelector('#record-inspector-title');
  const inspectorContext = document.querySelector('#record-inspector-context');
  const inspectorBody = document.querySelector('#record-inspector-body');
  const inspectorWorkspace = document.querySelector('#record-inspector-workspace');
  const attentionStates = new Set(['pending','submitted','blocked','exception','review required','rejected','on hold','broken','over limit','overdue','expired','unmatched']);
  let approvals = [];
  let loading = false;
  let inspectorRoute = '';

  const clean = value => String(value || '').trim().replace(/\s+/g, ' ');
  const route = () => location.hash.slice(1).split('?')[0] || 'overview';
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const clear = node => { while (node.firstChild) node.firstChild.remove(); };

  function localSignals() {
    const found = [];
    const seen = new Set();
    content.querySelectorAll('.status').forEach(status => {
      const state = clean(status.textContent).toLowerCase().replaceAll('_', ' ');
      if (!attentionStates.has(state)) return;
      const row = status.closest('tr.inspectable-row');
      const host = row || status.closest('.panel,.metric');
      if (!host || seen.has(host)) return;
      seen.add(host);
      const panel = host.closest('.panel');
      found.push({
        state,
        title: clean(row?.querySelector('td')?.textContent || panel?.querySelector('.panel-head h3,h3')?.textContent || document.querySelector('#page-title')?.textContent),
        detail: clean(row?.children?.[1]?.textContent || panel?.querySelector('.panel-head span')?.textContent || 'Review this workspace signal'),
        row,
      });
    });
    return found.slice(0, 25);
  }

  function updateCount() {
    const local = localSignals().length;
    const actionable = approvals.filter(item => item.action_eligible).length;
    const total = local + actionable;
    attentionCount.textContent = String(total);
    attentionCount.setAttribute('aria-label', `${total} items requiring attention`);
    attentionTrigger.dataset.clear = total ? 'false' : 'true';
    attentionTrigger.setAttribute('aria-label', total ? `Open attention center, ${total} items` : 'Open attention center, no current items');
  }

  function addAttentionSection(title, description, items, renderer) {
    const section = element('section', 'drawer-section');
    section.append(element('h3', '', title), element('p', '', description));
    if (!items.length) section.append(element('div', 'drawer-empty', 'No items currently require attention.'));
    else items.forEach(item => section.append(renderer(item)));
    attentionItems.append(section);
  }

  function renderAttention() {
    const local = localSignals();
    const actionable = approvals.filter(item => item.action_eligible);
    const waiting = approvals.filter(item => !item.action_eligible);
    clear(attentionSummary);
    [['Actionable approvals', actionable.length], ['Current workspace signals', local.length], ['Independent approval', waiting.length]].forEach(([label, value]) => attentionSummary.append(element('span', '', `${label}: ${value}`)));
    clear(attentionItems);
    addAttentionSection('Actionable approvals', 'Only records inside your current permission and location scope.', actionable, item => {
      const button = element('button', 'attention-item');
      button.type = 'button';
      const copy = element('span');
      copy.append(element('b', '', `${item.workflow} · ${item.reference}`), element('small', '', `${item.location_code || 'Company-wide'} · submitted by ${item.submitted_by || 'System'}`));
      button.append(copy, element('span', '', clean(item.status).replaceAll('_', ' ')));
      button.onclick = () => { attentionDialog.close(); location.hash = item.route; };
      return button;
    });
    addAttentionSection('Current workspace signals', 'Visible blocked, exception, overdue, rejected or pending records on this page.', local, item => {
      const button = element('button', 'attention-item');
      button.type = 'button';
      const copy = element('span');
      copy.append(element('b', '', item.title || 'Workspace record'), element('small', '', item.detail));
      button.append(copy, element('span', '', item.state));
      button.onclick = () => { attentionDialog.close(); if (item.row) openInspector(item.row); };
      return button;
    });
    addAttentionSection('Awaiting another approver', 'Your own submissions remain visible but cannot be self-approved.', waiting, item => {
      const button = element('button', 'attention-item');
      button.type = 'button';
      const copy = element('span');
      copy.append(element('b', '', `${item.workflow} · ${item.reference}`), element('small', '', 'Independent approver required'));
      button.append(copy, element('span', '', clean(item.status).replaceAll('_', ' ')));
      button.onclick = () => { attentionDialog.close(); location.hash = item.route; };
      return button;
    });
    updateCount();
  }

  async function loadApprovals() {
    if (loading || !document.querySelector('#signed-in-user')?.textContent.trim()) return;
    loading = true;
    try {
      const response = await fetch('/api/v1/my-workspace', {headers: {'Accept': 'application/json'}});
      if (response.ok) approvals = (await response.json()).items || [];
    } catch (_) {
      approvals = [];
    } finally {
      loading = false;
      renderAttention();
    }
  }

  function openInspector(row) {
    const table = row.closest('table');
    const panel = row.closest('.panel');
    const headers = [...table.querySelectorAll('thead th')].map(cell => clean(cell.textContent));
    const cells = [...row.children].map(cell => clean(cell.textContent));
    const reference = cells[0] || 'Record';
    inspectorRoute = route();
    inspectorTitle.textContent = reference;
    inspectorContext.textContent = `${document.querySelector('#page-title')?.textContent.trim() || 'Workspace'} · ${panel?.querySelector('.panel-head h3,h3')?.textContent.trim() || 'Record details'}`;
    clear(inspectorBody);
    const section = element('section', 'drawer-section');
    section.append(element('h3', '', 'Visible record fields'));
    const grid = element('dl', 'record-inspector-grid');
    cells.forEach((value, index) => {
      if (!value) return;
      grid.append(element('dt', '', headers[index] || `Field ${index + 1}`), element('dd', '', value));
    });
    section.append(grid);
    const actions = [...row.querySelectorAll('button,a.button')].map(item => clean(item.textContent)).filter(Boolean);
    const note = clean(panel?.querySelector('.control-note,.footer-note')?.textContent);
    if (actions.length || note) {
      const evidence = element('div', 'inspector-evidence');
      evidence.append(element('b', '', actions.length ? 'Available controlled actions' : 'Control evidence'), element('p', '', actions.length ? actions.join(' · ') : note));
      if (actions.length && note) evidence.append(element('p', '', note));
      section.append(evidence);
    }
    inspectorBody.append(section);
    inspector.showModal();
  }

  content.addEventListener('click', event => {
    if (event.target.closest('button,a,input,select,textarea,label,summary')) return;
    const row = event.target.closest('tr.inspectable-row');
    if (row) openInspector(row);
  });
  content.addEventListener('keydown', event => {
    if (!['Enter', ' '].includes(event.key) || event.target.closest('button,a,input,select,textarea')) return;
    const row = event.target.closest('tr.inspectable-row');
    if (!row) return;
    event.preventDefault();
    openInspector(row);
  });
  attentionTrigger.onclick = async () => { renderAttention(); attentionDialog.showModal(); await loadApprovals(); };
  inspectorWorkspace.onclick = () => { inspector.close(); if (inspectorRoute && route() !== inspectorRoute) location.hash = inspectorRoute; else content.focus(); };
  const schedule = (() => { let pending = false; return () => { if (pending) return; pending = true; queueMicrotask(() => { pending = false; updateCount(); if (attentionDialog.open) renderAttention(); }); }; })();
  new MutationObserver(schedule).observe(content, {childList: true, subtree: true});
  const identity = document.querySelector('#signed-in-user');
  new MutationObserver(loadApprovals).observe(identity, {childList: true, subtree: true, characterData: true});
  schedule();
  loadApprovals();
})();
