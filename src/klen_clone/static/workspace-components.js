/* Shared workspace presentation primitives. No API calls or workflow mutations. */
(() => {
  'use strict';

  const addClasses = (element, classes = []) => {
    if (!element) return element;
    const values = Array.isArray(classes) ? classes : String(classes).split(/\s+/);
    element.classList.add(...values.filter(Boolean));
    return element;
  };
  const readableText = element => [...element.childNodes]
    .map(child => child.nodeType === 3 ? child.textContent : (child.innerText || child.textContent))
    .join(' ').trim().replace(/\s+/g, ' ');

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
    let heading = element.querySelector(options.headingSelector || '.panel-head');
    const directTitle = !heading && element.querySelector(':scope > h3');
    if (directTitle) {
      heading = document.createElement('div');
      heading.className = 'panel-head';
      directTitle.before(heading);
      heading.append(directTitle);
    }
    addClasses(heading, 'section-heading');
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

  const taskSlug = value => String(value || 'workspace')
    .toLocaleLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '').slice(0, 54) || 'workspace';

  const taskTitle = (element, fallback) => {
    const heading = element.querySelector([
      ':scope > .panel-head h3', ':scope > h3', ':scope > h2',
      ':scope > summary h3', ':scope > summary', '.panel-head h3', '.section-title'
    ].join(','));
    const value = heading?.textContent?.trim().replace(/\s+/g, ' ');
    if (value) return value;
    if (element.matches('.workflow-steps')) return 'Process';
    if (element.matches('.review-workspace')) return 'Review queue';
    if (element.matches('.statement-grid')) return 'Statements';
    if (element.matches('.ageing-filter-panel')) return 'Report filters';
    if (element.matches('.statement-filter-panel')) return 'Statement filters';
    if (element.matches('.statement-empty-panel')) return 'Statement preview';
    if (element.querySelector(':scope > form.filters,:scope > .central-filter-form')) return 'Filters';
    if (element.matches('.central-empty,.empty')) return 'Current queue';
    return fallback;
  };

  const operationalFormPanel = element => {
    if (!element.matches('.panel,.workspace-section')) return false;
    const forms = [...element.querySelectorAll('form')].filter(form =>
      !form.matches('.filters,.central-filter-form,.ledger-filter') &&
      !form.closest('dialog,.reason-dialog-backdrop'));
    if (!forms.length) return false;
    const title = taskTitle(element, '');
    const actionTitle = /\b(create|capture|prepare|new|register|request|record|plan|open|start|configure|maintain|entry|draft|adjustment|operation)\b/i;
    if (!actionTitle.test(title)) return false;
    return [...element.querySelectorAll('.table-wrap')].every(region => Boolean(region.closest('form')));
  };

  const taskWorkspace = (root, options = {}) => {
    if (!root || root.querySelector(':scope > .workspace-taskbar')) return null;
    const route = options.route || root.dataset?.workspace || 'workspace';
    const direct = [...root.children];
    const actionPanels = direct.filter(operationalFormPanel);
    const excluded = element => element.matches([
      '.workspace-hero', '.central-metrics', '.loading', '.error',
      '.ledger-warning', '.workspace-taskbar', '.workspace-action-drawer'
    ].join(',')) || actionPanels.includes(element);
    const pending = [];
    const sections = [];
    direct.filter(element => !excluded(element)).forEach(element => {
      if (element.hidden || element.matches('.central-toolbar,.workflow-steps,.review-guide')) {
        pending.push(element);
        return;
      }
      if (element.matches('.pagination,.footer-note,.control-note,.central-note') && sections.length) {
        sections[sections.length - 1].nodes.push(element);
        return;
      }
      sections.push({nodes: [...pending.splice(0), element]});
    });
    if (pending.length && sections.length) sections[sections.length - 1].nodes.push(...pending);
    if (sections.length < 2 && !actionPanels.length) return null;

    root.classList.add('has-task-workspace');
    const bar = document.createElement('div');
    bar.className = 'workspace-taskbar';
    bar.setAttribute('aria-label', `${options.title || 'Workspace'} tasks and actions`);
    const tabs = document.createElement('div');
    tabs.className = 'workspace-task-tabs';
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', `${options.title || 'Workspace'} views`);
    const panes = document.createElement('div');
    panes.className = 'workspace-task-panes';
    const usedTitles = new Map();
    const tabItems = sections.map((section, index) => {
      const baseTitle = taskTitle(section.nodes.find(node => !node.matches('.central-toolbar,.workflow-steps,.review-guide')) || section.nodes[0], `Workspace ${index + 1}`);
      const occurrence = (usedTitles.get(baseTitle) || 0) + 1;
      usedTitles.set(baseTitle, occurrence);
      const label = occurrence > 1 ? `${baseTitle} ${occurrence}` : baseTitle;
      const key = `${taskSlug(baseTitle)}-${index + 1}`;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'workspace-task-tab';
      button.id = `workspace-tab-${taskSlug(route)}-${index + 1}`;
      button.dataset.taskView = key;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', `workspace-pane-${taskSlug(route)}-${index + 1}`);
      const buttonLabel = document.createElement('span');
      buttonLabel.textContent = label;
      button.append(buttonLabel);
      const pane = document.createElement('section');
      pane.className = 'workspace-task-pane';
      pane.id = `workspace-pane-${taskSlug(route)}-${index + 1}`;
      pane.dataset.taskView = key;
      pane.setAttribute('role', 'tabpanel');
      pane.setAttribute('aria-labelledby', button.id);
      section.nodes.forEach(node => pane.append(node));
      tabs.append(button);
      panes.append(pane);
      return {button, pane, key};
    });

    const locationParams = new URLSearchParams((location.hash.split('?')[1] || ''));
    const storageKey = `asas.workspace.view.v2:${route}`;
    let storedView = '';
    try { storedView = sessionStorage.getItem(storageKey) || ''; } catch { /* Storage may be unavailable. */ }
    const requestedView = locationParams.get('view') || storedView;
    const preferred = tabItems.find(item => item.pane.querySelector('table') && !item.pane.querySelector('form')) || tabItems[0];
    const initial = tabItems.find(item => item.key === requestedView) || preferred;
    const activate = (item, {focus = false, persist = true} = {}) => {
      if (!item) return;
      tabItems.forEach(candidate => {
        const active = candidate === item;
        candidate.button.setAttribute('aria-selected', String(active));
        candidate.button.tabIndex = active ? 0 : -1;
        candidate.pane.hidden = !active;
        candidate.pane.toggleAttribute('inert', !active);
      });
      root.dataset.activeTask = item.key;
      if (persist) {
        try { sessionStorage.setItem(storageKey, item.key); } catch { /* Storage may be unavailable. */ }
        const [hashRoute] = location.hash.slice(1).split('?');
        const params = new URLSearchParams(location.hash.split('?')[1] || '');
        params.set('view', item.key);
        history.replaceState(null, '', `${location.pathname}${location.search}#${hashRoute || route}?${params}`);
      }
      if (focus) item.button.focus();
    };
    tabItems.forEach((item, index) => {
      item.button.addEventListener('click', () => activate(item));
      item.button.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let target = index;
        if (event.key === 'ArrowLeft') target = (index - 1 + tabItems.length) % tabItems.length;
        if (event.key === 'ArrowRight') target = (index + 1) % tabItems.length;
        if (event.key === 'Home') target = 0;
        if (event.key === 'End') target = tabItems.length - 1;
        activate(tabItems[target], {focus: true});
      });
    });
    activate(initial, {persist: false});

    const actions = document.createElement('div');
    actions.className = 'workspace-task-actions';
    const drawers = actionPanels.map((panelElement, index) => {
      const label = taskTitle(panelElement, `New record ${index + 1}`);
      const dialog = document.createElement('dialog');
      dialog.className = 'workspace-action-drawer';
      dialog.id = `workspace-action-${taskSlug(route)}-${index + 1}`;
      dialog.setAttribute('aria-labelledby', `${dialog.id}-title`);
      const head = document.createElement('div');
      head.className = 'workspace-action-head';
      const copy = document.createElement('div');
      const eyebrow = document.createElement('p');
      eyebrow.className = 'eyebrow'; eyebrow.textContent = 'FOCUSED TASK';
      const title = document.createElement('h2');
      title.id = `${dialog.id}-title`; title.textContent = label;
      const detail = document.createElement('p');
      detail.textContent = 'Complete this task without losing your current register or filters.';
      copy.append(eyebrow, title, detail);
      const close = document.createElement('button');
      close.type = 'button'; close.className = 'workspace-action-close'; close.textContent = '×';
      close.setAttribute('aria-label', `Close ${label}`);
      close.addEventListener('click', () => dialog.close());
      head.append(copy, close);
      const body = document.createElement('div');
      body.className = 'workspace-action-body';
      body.append(panelElement);
      dialog.append(head, body);
      dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
      dialog.addEventListener('close', () => { delete document.documentElement.dataset.taskDrawer; });
      root.append(dialog);
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'workspace-action-launcher'; button.textContent = label;
      button.setAttribute('aria-controls', dialog.id);
      button.addEventListener('click', () => {
        document.documentElement.dataset.taskDrawer = 'open';
        dialog.showModal();
      });
      return {button, dialog, label};
    });
    if (drawers.length === 1) {
      drawers[0].button.classList.add('primary');
      actions.append(drawers[0].button);
    } else if (drawers.length > 1) {
      const menu = document.createElement('details');
      menu.className = 'workspace-action-menu';
      const summary = document.createElement('summary');
      summary.textContent = 'New or prepare';
      const options = document.createElement('div');
      options.className = 'workspace-action-options';
      drawers.forEach(item => {
        item.button.addEventListener('click', () => { menu.open = false; });
        options.append(item.button);
      });
      menu.append(summary, options);
      actions.append(menu);
    }
    if (tabItems.length) bar.append(tabs);
    if (drawers.length) bar.append(actions);
    const anchor = root.querySelector(':scope > .central-metrics') || root.querySelector(':scope > .workspace-hero');
    if (anchor) anchor.after(bar); else root.prepend(bar);
    if (tabItems.length) bar.after(panes);
    return {bar, panes, drawers};
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
      const legacyFields = [...element.querySelectorAll(':scope > .draft-fields:not(.form-grid)')];
      if (legacyFields.length) {
        addClasses(element, 'legacy-workspace-form');
        legacyFields.forEach(fields => addClasses(fields, ['form-grid', 'central-form-grid']));
        addClasses(element.querySelector(':scope > h4'), 'form-section-title');
        const submit = element.querySelector(':scope > button.primary');
        if (submit && !submit.parentElement?.classList.contains('action-bar')) {
          const actions = document.createElement('div');
          actions.className = 'action-bar legacy-form-actions';
          submit.before(actions);
          actions.append(submit);
        }
      }
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
        const firstCell = row.querySelector('td');
        const reference = firstCell ? readableText(firstCell).slice(0, 120) : '';
        row.setAttribute('aria-label', reference ? `Inspect ${reference}` : 'Inspect record');
      }
    });
    root.querySelectorAll('td.money').forEach(element => addClasses(element, 'financial-cell'));
    root.querySelectorAll('.row-actions,.draft-actions,.review-actions').forEach(element => addClasses(element, 'central-action-cluster'));
    root.querySelectorAll('.empty').forEach(element => addClasses(element, 'central-empty'));
    root.querySelectorAll('.footer-note').forEach(element => addClasses(element, 'central-note'));
    root.querySelectorAll('details').forEach(element => addClasses(element, 'central-details'));
    taskWorkspace(root, options);
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

  window.WorkspaceUI = Object.freeze({addClasses, caption, controlNote, feedback, findPanel, form, migrate, observe, panel, taskWorkspace, workflow});
})();
