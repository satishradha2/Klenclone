(() => {
  const pageSize = 25;

  function enhance(table) {
    if (table.dataset.serverPaginated || table.dataset.clientPaginated || table.closest('.draft-lines')) return;
    table.dataset.clientPaginated = 'true';
    const rows = [...table.tBodies].flatMap(body => [...body.rows]);
    if (rows.length <= pageSize || rows.some(row => row.querySelector('.empty'))) return;
    const pages = Math.ceil(rows.length / pageSize);
    let page = 1;
    const controls = document.createElement('nav');
    controls.className = 'pagination client-pagination';
    controls.setAttribute('aria-label', 'Table pages');
    table.closest('.table-wrap').insertAdjacentElement('afterend', controls);

    function render() {
      const start = (page - 1) * pageSize;
      const end = Math.min(rows.length, start + pageSize);
      rows.forEach((row, index) => { row.hidden = index < start || index >= end; });
      controls.innerHTML = `<span>Showing ${start + 1}–${end} of ${rows.length}</span><button type="button" data-action="previous" ${page === 1 ? 'disabled' : ''}>Previous</button><b>Page ${page} of ${pages}</b><button type="button" data-action="next" ${page === pages ? 'disabled' : ''}>Next</button>`;
      controls.querySelector('[data-action="previous"]').onclick = () => { if (page > 1) { page -= 1; render(); table.scrollIntoView({behavior:'smooth',block:'start'}); } };
      controls.querySelector('[data-action="next"]').onclick = () => { if (page < pages) { page += 1; render(); table.scrollIntoView({behavior:'smooth',block:'start'}); } };
    }
    render();
  }

  function scan(root = document) {
    if (root.matches?.('.table-wrap table')) enhance(root);
    root.querySelectorAll?.('.table-wrap table').forEach(enhance);
  }

  scan();
  new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
    if (node.nodeType === Node.ELEMENT_NODE) scan(node);
  }))).observe(document.body, {childList:true,subtree:true});
})();
