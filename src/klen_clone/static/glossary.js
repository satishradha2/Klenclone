(() => {
  const definitions = Object.freeze({
    PROVISIONAL_OVERLAY: 'This record comes from a later checksum-verified BizModo capture layered over the baseline. It is visible for review but is not included in permanent posting yet.',
    MIGRATION_LOCKED_READY: 'The migrated record passed structural controls and is protected from uncontrolled changes. Governed ERP edit, deactivate and reactivate actions remain available.',
    CONTROLLED_STAGING: 'A working ERP environment for verified data and controlled workflows. Permanent accounting and stock posting is still locked.',
    ACTIVE: 'The master record is available for new ERP transactions.',
    INACTIVE: 'The master record is retained for history but cannot be selected for new transactions.',
    DRAFT: 'A saved working document with no permanent stock or ledger effect.',
    SUBMITTED: 'The document is locked for review and waiting for an authorized approver.',
    APPROVED: 'An authorized approver accepted the document. Permanent posting may still require a separate action.',
    ACCEPTED: 'The goods receipt passed inspection and is eligible for the next controlled step.',
    REJECTED: 'The document or received quantity failed review and cannot proceed without correction.',
    CANCELLED: 'The document was stopped and retained in the audit history without permanent posting.',
    POSTED: 'The approved document created permanent accounting, stock or subledger entries.',
    REVERSED: 'A controlled opposite posting neutralized the original posting while preserving both audit records.',
    OPEN: 'The item still requires review, resolution, allocation or closure.',
    BLOCKED: 'A control failure prevents this record from moving to the next workflow stage.',
    EXCEPTION: 'A data or control difference requires review before production activation.',
    REVIEW_REQUIRED: 'The value did not satisfy an automatic reconciliation rule and needs authorized review.',
    VERIFIED: 'The supporting control, checksum or reconciliation test passed.',
    IN_REVIEW: 'An authorized user opened this captured record for verification. No source, stock or accounting value has changed.',
    CORRECTION_REQUIRED: 'The reviewer found a problem. A corrected value and explanation must be recorded before verification.',
    CORRECTED: 'A proposed corrected value is stored separately from the preserved source evidence and now requires verification.',
    PROMOTED: 'The governed migration process accepted the record into permanent ERP history after all required controls passed.',
    PROVISIONAL: 'The value is retained for review but is not approved as a final posted balance.',
    OPERATIONAL: 'The record has been promoted into the new ERP rules and can participate in authorized workflows.',
    POSTING_DISABLED: 'Permanent stock and accounting writes are locked. Drafting, approvals and posting rehearsals can still operate.',
    NON_ATOMIC: 'The source was captured while BizModo could still change, so the files may not represent one exact instant.',
    CHECKSUM_VERIFIED: 'The file fingerprint matches the recorded fingerprint, showing that the captured file has not changed.',
    ATOMIC_CAPTURE: 'A source snapshot taken at one consistent point with business transactions paused or a database-level backup used.',
    AR_AP: 'Accounts Receivable and Accounts Payable: money customers owe the business and money the business owes suppliers.',
    AGEING: 'Outstanding customer or supplier balances grouped by how long they have remained unpaid.',
    GL: 'General Ledger: the central accounting record containing debit and credit entries by account.',
    VAT: 'Value Added Tax recorded on taxable sales and purchases.',
    UOM: 'Unit of Measure, such as piece, box, carton, kilogram or litre.',
    GRNI: 'Goods Received Not Invoiced: a temporary liability for goods received before the supplier invoice is posted.',
    OPENING_BALANCE: 'The approved balance brought into the ERP at the migration cutover date.',
    REHEARSAL: 'A rollback-safe simulation that validates entries and balances without making a permanent posting.',
    RESERVATION: 'Stock quantity temporarily protected for a document so it cannot be allocated twice.',
    WRITE_OFF: 'Quantity or value removed because it cannot be sold or recovered, with an auditable reason.',
    RESTOCK: 'Returned quantity accepted back into saleable inventory.',
    ADVANCE: 'Money received from a customer or paid to a supplier before it is allocated to a specific invoice.',
    ALLOCATED: 'The portion of a receipt or payment matched to one or more outstanding documents.',
    REVISION: 'The document version used to prevent one user from silently overwriting another user’s changes.',
    SOURCE_LINEAGE: 'The trace linking an ERP record back to its captured BizModo source and checksum.',
  });

  const normalize = value => String(value || '').trim().toUpperCase()
    .replace(/&/g, ' AND ').replace(/[\s\-/]+/g, '_').replace(/[^A-Z0-9_]/g, '')
    .replace(/_+/g, '_').replace(/^_|_$/g, '');
  const phrases = Object.keys(definitions).sort((a, b) => b.length - a.length);
  const selectors = '.status,.badge,.preview-pill,.snapshot,.source-card b,.notice b,.metric small,.metric em,.panel-head span,.footer-note,th';
  const statusLabels = Object.freeze({
    PROVISIONAL_OVERLAY: 'Later capture — details pending',
    MIGRATION_LOCKED_READY: 'Verified migrated record',
    REVIEW_REQUIRED: 'Needs review', REVIEW_REQUIRED_SOURCE_LOGIC: 'Needs accounting review',
    IN_REVIEW: 'Review in progress', CORRECTION_REQUIRED: 'Correction required',
    CORRECTED: 'Correction saved', VERIFIED: 'Verified', REJECTED: 'Rejected',
    PROMOTED: 'Permanent ERP record', BLOCKED: 'Blocked', EXCEPTION: 'Needs attention',
    DRAFT: 'Draft', SUBMITTED: 'Awaiting approval', APPROVED: 'Approved',
    CANCELLED: 'Cancelled', POSTED: 'Posted', REVERSED: 'Reversed',
    ACTIVE: 'Active', INACTIVE: 'Inactive'
  });

  function description(text) {
    const key = normalize(text);
    if (definitions[key]) return definitions[key];
    const phrase = phrases.find(item => key.includes(item));
    return phrase ? definitions[phrase] : '';
  }

  function annotate(root = document) {
    const nodes = root.matches?.(selectors) ? [root] : [...(root.querySelectorAll?.(selectors) || [])];
    nodes.forEach(node => {
      if (node.dataset.erpHelp) return;
      const originalText = node.textContent;
      const key = normalize(originalText);
      const help = description(originalText);
      if (!help) return;
      if (node.matches('.status')) {
        node.dataset.erpStatus = originalText.trim();
        node.textContent = statusLabels[key] || originalText.trim().replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase());
      }
      node.dataset.erpHelp = help;
      node.setAttribute('title', help);
      node.setAttribute('tabindex', node.getAttribute('tabindex') || '0');
      node.setAttribute('aria-description', help);
    });
  }

  const tooltip = document.createElement('div');
  tooltip.id = 'erp-glossary-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  document.body.appendChild(tooltip);

  function show(target) {
    tooltip.textContent = target.dataset.erpHelp;
    tooltip.classList.add('visible');
    const box = target.getBoundingClientRect();
    const left = Math.min(Math.max(8, box.left), window.innerWidth - tooltip.offsetWidth - 8);
    let top = box.bottom + 8;
    if (top + tooltip.offsetHeight > window.innerHeight - 8) top = Math.max(8, box.top - tooltip.offsetHeight - 8);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
    target.setAttribute('aria-describedby', tooltip.id);
  }
  function hide(target) {
    tooltip.classList.remove('visible');
    target?.removeAttribute('aria-describedby');
  }

  document.addEventListener('mouseover', event => { const target = event.target.closest?.('[data-erp-help]'); if (target) show(target); });
  document.addEventListener('mouseout', event => { const target = event.target.closest?.('[data-erp-help]'); if (target && !target.contains(event.relatedTarget)) hide(target); });
  document.addEventListener('focusin', event => { const target = event.target.closest?.('[data-erp-help]'); if (target) show(target); });
  document.addEventListener('focusout', event => { const target = event.target.closest?.('[data-erp-help]'); if (target) hide(target); });

  annotate();
  new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
    if (node.nodeType === Node.ELEMENT_NODE) annotate(node);
  }))).observe(document.body, {childList: true, subtree: true});
})();
