/* Test-owned Workday widget emulation for the synthetic llm_fill fixture pages (Q-35 WP-T1).
 * The pages copy Workday's DOM (data-automation-id, aria-*, role); this script adds the
 * behaviour the static markup lacks. Data comes from <script type="application/json" id="shim-data">:
 *   options: {controlId: ["A", "B", {"cat": "Category", "items": ["Leaf 1", "Leaf 2"]}]}
 *   search:  {controlId: true}      options appear only after typing + Enter in the prompt box
 *   drop:    {controlId: "always" | "once"}  listbox shows the text but keeps no value (S-5b #6)
 *   reveal:  {controlId: {"when": "Yes", "show": "<element id>"}}   (review H7)
 *   next:    "../NN-step/page.html"  where a clean Next goes; "" on the review page
 * Counters for oracles: body[data-submit-count], body[data-form-submits], body[data-next-clicks].
 * No network, no timers beyond 0 ms.
 */
(() => {
  const el = document.getElementById('shim-data');
  const D = el ? JSON.parse(el.textContent) : {};
  const opts = D.options || {}, search = D.search || {}, drop = D.drop || {}, reveal = D.reveal || {};
  const dropped = {};
  const B = document.body;
  for (const k of ['submitCount', 'formSubmits', 'nextClicks']) B.dataset[k] = B.dataset[k] || '0';
  const bump = k => { B.dataset[k] = String(+B.dataset[k] + 1); };
  const ff = n => n.closest('[data-automation-id^="formField-"]');
  let popup = null;
  const close = () => { if (popup) { popup.remove(); popup = null; } };
  const flat = list => list.flatMap(o => typeof o === 'string' ? [o] : o.items);

  function setError(field, msg) {
    if (!field) return;
    let a = field.querySelector('[data-automation-id="inputAlert"]');
    const ctl = field.querySelector('input:not([type=hidden]), textarea, button[aria-haspopup="listbox"]');
    if (!msg) { if (a) a.remove(); if (ctl) ctl.setAttribute('aria-invalid', 'false'); return; }
    if (!a) {
      a = document.createElement('div');
      a.setAttribute('data-automation-id', 'inputAlert');
      a.setAttribute('role', 'alert');
      a.id = 'alert-' + (field.getAttribute('data-automation-id') || 'f') + '-' + Math.floor(Math.random() * 1e6);
      field.appendChild(a);
    }
    a.textContent = msg;
    if (ctl) { ctl.setAttribute('aria-invalid', 'true'); ctl.setAttribute('aria-describedby', a.id); }
  }

  function showPopup(anchor, items, onPick, isPrompt) {
    close();
    popup = document.createElement('div');
    popup.setAttribute('data-automation-id', 'activeListContainer');
    popup.style.cssText = 'position:absolute;background:#fff;border:1px solid #888;z-index:10;min-width:200px';
    const r = anchor.getBoundingClientRect();
    popup.style.left = (r.left + window.scrollX) + 'px';
    popup.style.top = (r.bottom + window.scrollY) + 'px';
    const ul = document.createElement(isPrompt ? 'div' : 'ul');
    ul.setAttribute('role', 'listbox');
    if (!items.length) {
      const li = document.createElement('div'); li.textContent = 'No Items.'; ul.appendChild(li);
    }
    for (const it of items) {
      const isCat = typeof it !== 'string';
      const text = isCat ? it.cat : it;
      const li = document.createElement(isPrompt ? 'div' : 'li');
      li.setAttribute('role', 'option');
      li.setAttribute('data-automation-label', text);
      li.style.cssText = 'padding:4px;cursor:pointer';
      if (isPrompt) {
        li.setAttribute('data-automation-id', 'menuItem');
        const p = document.createElement('div');
        p.setAttribute('data-automation-id', isCat ? 'promptOption' : 'promptLeafNode');
        const inner = document.createElement('div');
        inner.setAttribute('data-automation-id', 'promptOption');
        inner.setAttribute('data-automation-label', text);
        inner.textContent = text;
        if (isCat) { p.removeAttribute('data-automation-id'); p.appendChild(inner); }
        else { p.appendChild(inner); }
        li.appendChild(p);
        if (isCat) {
          const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          svg.setAttribute('class', 'wd-icon-chevron-right-small wd-icon');
          svg.setAttribute('width', '12'); svg.setAttribute('height', '12');
          li.appendChild(svg);
        }
      } else {
        const d = document.createElement('div'); d.textContent = text; li.appendChild(d);
      }
      li.addEventListener('click', ev => {
        ev.stopPropagation();
        if (isCat) {
          const title = document.createElement('div');
          title.setAttribute('data-automation-id', 'promptTitle');
          title.textContent = it.cat;
          showPopup(anchor, it.items, onPick, true);
          popup.prepend(title);
        } else { onPick(text); }
      });
      ul.appendChild(li);
    }
    popup.appendChild(ul);
    document.body.appendChild(popup);
  }

  // ---- ARIA listbox (Workday "Select One" button + a hidden text input that holds the value)
  document.querySelectorAll('button[aria-haspopup="listbox"]').forEach(btn => {
    if (btn.closest('[data-automation-id="header"]')) return;
    btn.addEventListener('click', ev => {
      ev.stopPropagation();
      const list = ['Select One', ...(opts[btn.id] || [])];
      showPopup(btn, list, text => {
        close();
        const hidden = btn.parentElement.querySelector('input[type="text"]');
        const field = ff(btn);
        btn.textContent = text;
        const mode = drop[btn.id];
        const keep = !(mode === 'always' || (mode === 'once' && !dropped[btn.id]));
        if (mode === 'once') dropped[btn.id] = true;
        if (hidden) hidden.value = (keep && text !== 'Select One') ? text : '';
        btn.setAttribute('value', hidden ? hidden.value : '');
        setError(field, keep ? '' : 'Error: The field ' + (field.querySelector('label') || {}).textContent + ' is required and must have a value.');
        doReveal(btn.id, text);
        btn.dispatchEvent(new Event('change', { bubbles: true }));
      }, false);
    });
  });

  // ---- Prompt (selectinput): pills, categories, search on Enter
  function addPill(input, text) {
    const field = ff(input);
    const list = field.querySelector('[data-automation-id="selectedItemList"]');
    const multi = !!field.querySelector('[data-automation-id="multiSelectContainer"][data-uxi-widget-type="multiselect"][aria-multiselectable="true"]');
    if (!multi) list.innerHTML = '';
    if ([...list.querySelectorAll('[data-automation-id="selectedItem"]')].some(p => p.title === text)) return;
    const li = document.createElement('li');
    li.setAttribute('role', 'presentation'); li.setAttribute('data-automation-id', 'menuItem');
    li.innerHTML = '<div role="option" data-automation-id="selectedItem" tabindex="-1">' +
      '<div data-automation-id="DELETE_charm" role="presentation" tabindex="-1">x</div>' +
      '<p data-automation-id="promptOption"></p></div>';
    const pill = li.firstChild;
    pill.title = text; pill.setAttribute('aria-label', text + ', press delete to clear value');
    pill.querySelector('p').textContent = text;
    list.appendChild(li);
    input.value = '';
    setError(field, '');
  }
  document.addEventListener('click', ev => {
    const charm = ev.target.closest('[data-automation-id="DELETE_charm"]');
    if (charm) { ev.stopPropagation(); charm.closest('li').remove(); return; }
  }, true);
  document.querySelectorAll('input[data-uxi-widget-type="selectinput"]').forEach(inp => {
    const open = items => showPopup(inp, items, text => { close(); addPill(inp, text); doReveal(inp.id, text); }, true);
    const all = () => opts[inp.id] || [];
    inp.addEventListener('click', ev => { ev.stopPropagation(); open(search[inp.id] ? [] : all()); });
    const icon = ff(inp) && ff(inp).querySelector('[data-automation-id="promptIcon"]');
    if (icon) icon.addEventListener('click', ev => { ev.stopPropagation(); open(search[inp.id] ? [] : all()); });
    inp.addEventListener('keydown', ev => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      const q = inp.value.trim().toLowerCase();
      open(flat(all()).filter(t => !q || t.toLowerCase().includes(q)));
    });
  });

  // ---- Segmented date: the display div mirrors the typed section value
  document.querySelectorAll('input[data-automation-id^="dateSection"]').forEach(inp => {
    inp.addEventListener('input', () => {
      const disp = document.getElementById(inp.dataset.display || '');
      if (disp) disp.textContent = inp.value;
      inp.setAttribute('aria-valuetext', inp.value || inp.getAttribute('aria-label'));
      setError(ff(inp), '');
    });
  });

  // ---- Upload: the file name appears in the container, input.files is emptied (S-5b)
  document.querySelectorAll('input[type="file"]').forEach(inp => {
    inp.addEventListener('change', () => {
      const box = inp.closest('[data-automation-id="attachments-FileUpload"]') || inp.parentElement;
      const name = inp.files && inp.files.length ? inp.files[0].name : '';
      if (!name) return;
      let item = box.querySelector('[data-automation-id="file-upload-item"]');
      if (!item) {
        item = document.createElement('div');
        item.setAttribute('data-automation-id', 'file-upload-item');
        item.innerHTML = '<div data-automation-id="file-upload-item-name"></div>' +
          '<div data-automation-id="file-upload-successful">Successfully Uploaded!</div>' +
          '<button type="button" data-automation-id="delete-file" aria-label="Delete file">Delete</button>';
        box.appendChild(item);
      }
      item.querySelector('[data-automation-id="file-upload-item-name"]').textContent = name;
      setTimeout(() => { inp.value = ''; }, 0);
      setError(ff(inp) || box, '');
    });
  });
  document.addEventListener('click', ev => {
    const del = ev.target.closest('[data-automation-id="delete-file"]');
    if (del) del.closest('[data-automation-id="file-upload-item"]').remove();
  });

  // ---- Repeated entries: Delete removes the panel; Add appends a blank one from the <template>
  document.addEventListener('click', ev => {
    const del = ev.target.closest('[data-automation-id="panel-set-delete-button"]');
    if (del) { del.closest('[role="group"][data-entry]').remove(); return; }
    const add = ev.target.closest('[data-automation-id="add-button"]');
    if (add) {
      const sec = add.closest('[role="group"][data-section]');
      const tpl = sec.querySelector('template');
      const n = sec.querySelectorAll('[role="group"][data-entry]').length + 1;
      const holder = document.createElement('div');
      holder.innerHTML = tpl.innerHTML.replace(/__N__/g, String(n));
      add.parentElement.before(holder.firstElementChild);
    }
  });

  // ---- Radios: reveal rules
  document.querySelectorAll('input[type="radio"]').forEach(r => r.addEventListener('change', () => {
    const g = r.closest('[aria-labelledby][id]');
    const lab = document.querySelector('label[for="' + r.id + '"]');
    if (g) doReveal(g.id, lab ? lab.textContent.trim() : r.value);
    setError(ff(r), '');
  }));
  function doReveal(id, value) {
    const rule = reveal[id];
    if (!rule) return;
    const t = document.getElementById(rule.show);
    if (t) t.hidden = value !== rule.when;
  }

  // ---- Next / Submit
  function empty(field) {
    const date = field.querySelectorAll('input[data-automation-id^="dateSection"]');
    if (date.length) return [...date].some(i => !i.value);
    const btn = field.querySelector('button[aria-haspopup="listbox"]');
    if (btn) { const h = btn.parentElement.querySelector('input[type="text"]'); return !(h && h.value); }
    if (field.querySelector('[data-automation-id="selectedItemList"]'))
      return !field.querySelector('[data-automation-id="selectedItem"]');
    const radios = field.querySelectorAll('input[type="radio"]');
    if (radios.length) return ![...radios].some(r => r.checked);
    const cb = field.querySelector('input[type="checkbox"]');
    if (cb) return !cb.checked;
    if (field.querySelector('input[type="file"]'))
      return !field.querySelector('[data-automation-id="file-upload-item-name"]');
    const t = field.querySelector('input, textarea');
    return !(t && t.value.trim());
  }
  const next = document.querySelector('[data-automation-id="pageFooterNextButton"], [data-automation-id="bottom-navigation-next-button"]');
  if (next) next.addEventListener('click', ev => {
    ev.preventDefault();
    if (/^submit$/i.test(next.textContent.trim())) { bump('submitCount'); return; }
    bump('nextClicks');
    let bad = 0;
    document.querySelectorAll('[data-automation-id="applyFlowPage"] [data-automation-id^="formField-"]').forEach(f => {
      if (f.closest('[hidden]') || f.hidden) return;
      const req = !!f.querySelector('abbr') || !!f.querySelector('[aria-required="true"]');
      if (!req) return;
      if (empty(f)) { bad++; setError(f, 'Error: ' + ((f.querySelector('label, legend') || {}).textContent || '').replace(/\*$/, '').trim() + ' is required.'); }
    });
    if (!bad && D.next) location.href = D.next;
  });

  // ---- Implicit form submission is counted (review M8: never press Enter inside a <form>)
  document.querySelectorAll('form').forEach(f => f.addEventListener('submit', ev => { ev.preventDefault(); bump('formSubmits'); }));
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape') close(); });
  document.addEventListener('click', ev => { if (popup && !popup.contains(ev.target)) close(); });
})();
