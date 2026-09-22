/* Shared workspace presentation primitives. No API calls or workflow mutations. */
(() => {
  'use strict';

  const addClasses = (element, classes = []) => {
    if (!element) return element;
    const values = Array.isArray(classes) ? classes : String(classes).split(/\s+/);
    element.classList.add(...values.filter(Boolean));
    return element;
  };

  const findPanel = (root, heading) => [...(root || document).querySelectorAll('.panel')]
    .find(panel => panel.querySelector('.panel-head h3')?.textContent.trim() === heading);

  const caption = (table, text) => {
    if (!table || !text) return null;
    const existing = table.querySelector('caption');
    if (existing) return existing;
    const element = document.createElement('caption');
    element.textContent = text;
    table.prepend(element);
    return element;
  };

  const feedback = (element, classes = []) => {
    if (!element) return null;
    addClasses(element, ['feedback', ...classes]);
    element.setAttribute('role', 'status');
    element.setAttribute('aria-live', 'polite');
    return element;
  };

  const workflow = ({anchor, className = '', label, steps = []}) => {
    if (!anchor || !steps.length) return null;
    const existing = anchor.previousElementSibling;
    if (existing?.classList.contains('workflow-steps')) return existing;
    const list = document.createElement('ol');
    addClasses(list, ['workflow-steps', className]);
    list.setAttribute('aria-label', label);
    steps.forEach((step, index) => {
      const item = document.createElement('li');
      const number = document.createElement('b');
      const copy = document.createElement('span');
      const detail = document.createElement('small');
      number.textContent = String(index + 1);
      copy.textContent = step.title;
      detail.textContent = step.detail;
      copy.append(detail);
      item.append(number, copy);
      list.append(item);
    });
    anchor.before(list);
    return list;
  };

  const panel = (element, options = {}) => {
    if (!element) return null;
    addClasses(element, ['workspace-section', ...(options.classes || [])]);
    addClasses(element.querySelector(options.headingSelector || '.panel-head'), 'section-heading');
    const table = element.querySelector(options.tableSelector || 'table');
    caption(table, options.caption);
    if (options.financialSelector) {
      element.querySelectorAll(options.financialSelector).forEach(cell => cell.classList.add('financial-cell'));
    }
    return element;
  };

  const form = (element, options = {}) => {
    if (!element) return null;
    const host = options.panel || element.closest('.panel');
    if (host) panel(host, {classes: options.panelClasses || []});
    addClasses(element, options.formClasses || ['transaction-form']);
    if (options.fields) addClasses(element.querySelector(options.fields), options.fieldClasses || ['form-grid']);
    if (options.lines) addClasses(element.querySelector(options.lines), options.lineClasses || ['line-editor']);
    if (options.notes) addClasses(element.querySelector(options.notes), options.noteClasses || []);
    if (options.actions) addClasses(element.querySelector(options.actions), options.actionClasses || ['action-bar']);
    if (options.wrapSubmit) {
      const submit = element.querySelector(options.wrapSubmit.selector || ':scope > button.primary');
      if (submit && !submit.parentElement?.classList.contains('action-bar')) {
        const actions = document.createElement('div');
        addClasses(actions, ['action-bar', ...(options.wrapSubmit.classes || [])]);
        submit.before(actions);
        actions.append(submit);
      }
    }
    (options.feedback || []).forEach(item => feedback(element.querySelector(item.selector || item), item.classes || []));
    if (options.caption) caption(element.querySelector(options.tableSelector || 'table'), options.caption);
    return element;
  };

  const controlNote = (container, text) => {
    if (!container || !text) return null;
    const existing = [...container.querySelectorAll(':scope > .control-note')].find(item => item.textContent === text);
    if (existing) return existing;
    const note = document.createElement('p');
    note.className = 'control-note';
    note.textContent = text;
    container.append(note);
    return note;
  };

  const migrate = (root = document, options = {}) => {
    if (!root) return null;
    addClasses(root, 'central-workspace');
    if (root.dataset && options.route) root.dataset.workspace = options.route;
    root.querySelectorAll('.hero').forEach(element => addClasses(element, 'workspace-hero'));
    root.querySelectorAll('.metrics').forEach(element => addClasses(element, 'central-metrics'));
    root.querySelectorAll('.grid-2').forEach(element => addClasses(element, 'central-grid'));
    root.querySelectorAll('.panel').forEach(element => panel(element));
    root.querySelectorAll('.toolbar').forEach(element => addClasses(element, 'central-toolbar'));
    root.querySelectorAll('.filters').forEach(element => addClasses(element, 'central-filter-form'));
    root.querySelectorAll('form').forEach(element => {
      if (element.closest('dialog,.reason-dialog-backdrop')) return;
      addClasses(element, 'central-form');
      element.querySelectorAll(':scope > .draft-fields,:scope > .form-grid').forEach(fields => addClasses(fields, 'central-form-grid'));
    });
    root.querySelectorAll('.table-wrap').forEach((region, index) => {
      addClasses(region, 'central-table-region');
      region.setAttribute('role', 'region');
      if (!region.hasAttribute('tabindex')) region.tabIndex = 0;
      if (!region.hasAttribute('aria-label')) {
        const heading = region.closest('.panel')?.querySelector('.panel-head h3')?.textContent.trim();
        region.setAttribute('aria-label', heading ? `${heading} table` : `${options.title || 'Workspace'} data table ${index + 1}`);
      }
    });
    root.querySelectorAll('table').forEach(element => addClasses(element, 'central-table'));
    root.querySelectorAll('.central-table tbody tr').forEach(row => {
      if (row.querySelector('.empty') || row.children.length < 2) return;
      addClasses(row, 'inspectable-row');
      if (!row.hasAttribute('tabindex')) row.tabIndex = 0;
      if (!row.hasAttribute('aria-label')) {
        const reference = row.querySelector('td')?.textContent.trim().replace(/\s+/g, ' ').slice(0, 120);
        row.setAttribute('aria-label', reference ? `Inspect ${reference}` : 'Inspect record');
      }
    });
    root.querySelectorAll('td.money').forEach(element => addClasses(element, 'financial-cell'));
    root.querySelectorAll('.row-actions,.draft-actions,.review-actions').forEach(element => addClasses(element, 'central-action-cluster'));
    root.querySelectorAll('.empty').forEach(element => addClasses(element, 'central-empty'));
    root.querySelectorAll('.footer-note').forEach(element => addClasses(element, 'central-note'));
    root.querySelectorAll('details').forEach(element => addClasses(element, 'central-details'));
    return root;
  };

  const observe = (root, context = () => ({})) => {
    if (!root || root.__workspaceObserver) return root?.__workspaceObserver || null;
    let scheduled = false;
    const render = () => {
      if (scheduled) return;
      scheduled = true;
      queueMicrotask(() => { scheduled = false; migrate(root, context() || {}); });
    };
    const observer = new MutationObserver(render);
    observer.observe(root, {childList: true, subtree: true});
    Object.defineProperty(root, '__workspaceObserver', {value: observer});
    render();
    return observer;
  };

  window.WorkspaceUI = Object.freeze({addClasses, caption, controlNote, feedback, findPanel, form, migrate, observe, panel, workflow});
})();
