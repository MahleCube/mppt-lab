(() => {
  'use strict';
  // Layout is independent of simulation configuration and never starts a calculation.
  const $ = id => document.getElementById(id);
  const mobile = matchMedia('(max-width: 600px)');
  const layout = $('lab-layout'), divider = $('pane-divider');
  let share = 50, drag = null;
  const scrollPositions = new Map();
  const requestDraw = () => window.dispatchEvent(new Event('lab:layout'));

  function showMobilePane(name) {
    document.body.dataset.mobilePane = name;
    document.querySelectorAll('[data-mobile-pane]').forEach(button => {
      if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', String(button.dataset.mobilePane === name));
    });
    requestAnimationFrame(requestDraw);
  }

  function selectTab(kind, key, focus = false) {
    const button = $(`${kind}-tab-${key}`), panel = $(`${kind}-panel-${key}`);
    if (!button || !panel) return;
    const container = document.querySelector(kind === 'setting' ? '.settings-content' : '.results-content');
    const active = document.querySelector(`[data-${kind}-tab][aria-selected="true"]`);
    if (active) scrollPositions.set(active.id, container.scrollTop);
    document.querySelectorAll(`[data-${kind}-tab]`).forEach(tab => {
      const selected = tab === button;
      tab.setAttribute('aria-selected', String(selected));
      tab.classList.toggle('active', selected);
      tab.tabIndex = selected ? 0 : -1;
      $(tab.getAttribute('aria-controls')).hidden = !selected;
    });
    container.scrollTop = scrollPositions.get(button.id) || 0;
    if (focus) button.focus();
    if (mobile.matches) showMobilePane(kind === 'setting' ? 'settings' : 'results');
    window.dispatchEvent(new CustomEvent('lab:tab', {detail:{kind,key}}));
    requestAnimationFrame(requestDraw);
  }

  ['setting', 'result'].forEach(kind => {
    const buttons = [...document.querySelectorAll(`[data-${kind}-tab]`)];
    buttons.forEach((button, index) => {
      button.addEventListener('click', () => selectTab(kind, button.dataset[`${kind}Tab`]));
      button.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % buttons.length;
        if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index + buttons.length - 1) % buttons.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = buttons.length - 1;
        if (next === undefined) return;
        event.preventDefault();
        selectTab(kind, buttons[next].dataset[`${kind}Tab`], true);
      });
    });
  });

  function limits() {
    // Keep both panes usable; the min width scales down on smaller desktops.
    const available = Math.max(1, layout.getBoundingClientRect().width - divider.offsetWidth);
    const min = Math.min(45, 340 / available * 100);
    return [min, 100 - min, available];
  }
  function setShare(value) {
    const [min, max] = limits();
    share = Math.max(min, Math.min(max, value));
    layout.style.setProperty('--left-size', `${share}fr`);
    layout.style.setProperty('--right-size', `${100 - share}fr`);
    divider.setAttribute('aria-valuemin', String(min));
    divider.setAttribute('aria-valuemax', String(max));
    divider.setAttribute('aria-valuenow', String(share));
    divider.setAttribute('aria-valuetext', `設定 ${Math.round(share)}%、データ ${100 - Math.round(share)}%`);
    requestDraw();
  }
  function finishDrag(event) {
    if (drag === null || (event && event.pointerId !== drag)) return;
    if (divider.hasPointerCapture(drag)) divider.releasePointerCapture(drag);
    drag = null;
    document.body.classList.remove('resizing-panes');
  }
  divider.addEventListener('pointerdown', event => {
    if (mobile.matches || !event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    drag = event.pointerId;
    divider.setPointerCapture(drag);
    divider.focus();
    document.body.classList.add('resizing-panes');
  });
  divider.addEventListener('pointermove', event => {
    if (event.pointerId !== drag) return;
    const [, , available] = limits();
    setShare((event.clientX - layout.getBoundingClientRect().left - divider.offsetWidth / 2) / available * 100);
  });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(name => divider.addEventListener(name, finishDrag));
  window.addEventListener('blur', () => finishDrag());
  divider.addEventListener('dblclick', () => setShare(50));
  divider.addEventListener('keydown', event => {
    let value;
    if (event.key === 'ArrowLeft') value = share - (event.shiftKey ? 5 : 1);
    if (event.key === 'ArrowRight') value = share + (event.shiftKey ? 5 : 1);
    if (event.key === 'Home') value = limits()[0];
    if (event.key === 'End') value = limits()[1];
    if (event.key === 'Enter') value = 50;
    if (value === undefined) return;
    event.preventDefault(); setShare(value);
  });
  $('reset-split').addEventListener('click', () => setShare(50));
  new ResizeObserver(() => { if (!mobile.matches) setShare(share); }).observe(layout);
  mobile.addEventListener('change', () => {
    finishDrag();
    if (!mobile.matches) setShare(share);
    requestAnimationFrame(requestDraw);
  });
  document.querySelectorAll('button[data-mobile-pane]').forEach(button => button.addEventListener('click', () => showMobilePane(button.dataset.mobilePane)));

  // Existing internal links must reveal a hidden tab before navigating to it.
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;
    const target = $(link.getAttribute('href').slice(1));
    const panel = target?.closest('[role="tabpanel"]');
    if (!panel) return;
    event.preventDefault();
    const kind = panel.classList.contains('setting-panel') ? 'setting' : 'result';
    selectTab(kind, panel.id.replace(`${kind}-panel-`, ''), true);
    if (target.id === 'algorithm-guide') window.PVLabHelp?.select('algorithm');
    if (target.tagName === 'DETAILS') target.open = true;
    target.scrollIntoView({block:'start'});
  });
  // Capture: show voltage before app.js scrolls to the selected measurement.
  $('timing-focus').addEventListener('click', () => selectTab('result', 'voltage'), true);
  const syncNotices = () => {
    $('comparison-empty').hidden = !$('comparison-card').hidden;
    $('warnings-details').hidden = $('warnings').hidden;
  };
  const notices = new MutationObserver(syncNotices);
  ['comparison-card', 'warnings'].forEach(id => notices.observe($(id), {attributes:true,attributeFilter:['hidden']}));
  syncNotices();
  document.querySelectorAll('.settings-content,.results-content').forEach(node => node.addEventListener('scroll', requestDraw, {passive:true}));
  window.PVLabLayout = {selectSetting:key=>selectTab('setting',key), selectResult:key=>selectTab('result',key), reset:()=>setShare(50)};
  setShare(50);
})();
