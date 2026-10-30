/* Visible choices backed by the existing select/change contract. */
(() => {
  'use strict';
  const records = new Map();
  const helpKeys = {
    preset:'preset', algorithm:'algorithm', experiment:'experiment',
    'plant-mode':'plant_mode', rtol:'rtol', 'mppt-method':'mppt_method',
    'custom-mppt':'mppt_method', 'custom-topology':'custom_topology',
    'custom-law':'custom_law', 'custom-voltage-mode':'voltage_mode',
    'custom-current-mode':'current_mode'
  };
  let queued = false;
  function scheduleRefresh() {
    if (queued) return;
    queued = true;
    queueMicrotask(() => { queued = false; refresh(); });
  }
  function labelText(select) {
    return select.getAttribute('aria-label') || select.id;
  }
  function focusChoice(record) {
    const buttons = [...record.group.querySelectorAll('[role="radio"]')].filter(button => !button.disabled);
    (buttons.find(button => button.getAttribute('aria-checked') === 'true') || buttons[0])?.focus();
  }
  function choose(record, button) {
    const {select} = record;
    if (button.disabled || select.disabled || select.value === button.dataset.choiceValue) return;
    select.value = button.dataset.choiceValue;
    select.dispatchEvent(new Event('change', {bubbles:true}));
    refresh();
  }
  function install(select) {
    if (!select.id || select.multiple || records.has(select)) return;
    const group = document.createElement('div');
    group.id = select.id + '-choices';
    group.className = 'choice-control';
    group.dataset.choiceFor = select.id;
    group.setAttribute('role', 'radiogroup');
    const help = select.dataset.helpKey || helpKeys[select.id];
    if (help) group.dataset.helpKey = help;
    const labels = [...select.labels];
    const labelledBy = select.getAttribute('aria-labelledby') || labels.map((label, index) => {
      if (!label.id) label.id = select.id + '-choice-label-' + index;
      return label.id;
    }).join(' ');
    if (labelledBy) group.setAttribute('aria-labelledby', labelledBy);
    else group.setAttribute('aria-label', labelText(select));
    // Chart selectors live inside labels; put the buttons outside those labels.
    (select.closest('label') || select).after(group);
    select.classList.add('choice-native-hidden');
    select.setAttribute('aria-hidden', 'true');
    select.tabIndex = -1;
    const record = {select, group, signature:'', buttons:[], status:null};
    records.set(select, record);
    for (const label of labels) {
      label.addEventListener('click', event => {
        if (event.target.closest('button,a,input') || select.disabled) return;
        event.preventDefault();
        focusChoice(record);
      });
    }
    group.addEventListener('click', event => {
      const button = event.target.closest('[data-choice-value]');
      if (button && group.contains(button)) choose(record, button);
    });
    group.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)) return;
      const buttons = record.buttons.filter(button => !button.disabled);
      if (!buttons.length) return;
      event.preventDefault();
      const index = buttons.indexOf(event.target);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
        : (Math.max(0, index) + (['ArrowLeft','ArrowUp'].includes(event.key) ? -1 : 1) + buttons.length) % buttons.length;
      buttons[next].focus();
      choose(record, buttons[next]);
    });
    select.addEventListener('change', scheduleRefresh);
    record.observer = new MutationObserver(scheduleRefresh);
    record.observer.observe(select, {subtree:true, childList:true, characterData:true, attributes:true,
      attributeFilter:['value','selected','disabled','hidden','label','aria-label','aria-labelledby']});
  }
  function optionDisabled(option, select) {
    return select.disabled || option.disabled || (option.parentElement.tagName === 'OPTGROUP' && option.parentElement.disabled);
  }
  function sync(record) {
    const {select, group} = record;
    group.hidden = select.hidden;
    group.setAttribute('aria-disabled', String(select.disabled));
    const signature = JSON.stringify([...select.children].map(node => node.tagName === 'OPTGROUP'
      ? ['group', node.label, node.hidden, [...node.children].map(option => [option.value, option.textContent, option.hidden])]
      : ['option', node.value, node.textContent, node.hidden]));
    if (signature !== record.signature) {
      const focusedValue = group.contains(document.activeElement) ? document.activeElement.dataset.choiceValue : null;
      const fragment = document.createDocumentFragment();
      record.buttons = [];
      record.status = null;
      if (select.id === 'preset') {
        record.status = document.createElement('p');
        record.status.className = 'choice-current-status';
        record.status.setAttribute('role', 'status');
        record.status.textContent = [...select.options].find(option => option.value === '')?.textContent || '現在の設定';
        fragment.append(record.status);
      }
      const addOptions = (options, parent) => {
        const grid = document.createElement('div');
        grid.className = 'choice-grid';
        for (const option of options) {
          if (option.hidden || (select.id === 'preset' && option.value === '')) continue;
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'choice-button';
          button.setAttribute('role', 'radio');
          button.dataset.choiceValue = option.value;
          button.textContent = option.textContent;
          grid.append(button);
          record.buttons.push(button);
        }
        if (grid.children.length) parent.append(grid);
      };
      let loose = [];
      const flush = () => { addOptions(loose, fragment); loose = []; };
      for (const node of select.children) {
        if (node.tagName === 'OPTION') loose.push(node);
        else if (node.tagName === 'OPTGROUP' && !node.hidden) {
          flush();
          const section = document.createElement('div');
          section.className = 'choice-option-group';
          const title = document.createElement('div');
          title.className = 'choice-group-name';
          title.textContent = node.label;
          section.append(title);
          addOptions([...node.children], section);
          fragment.append(section);
        }
      }
      flush();
      group.replaceChildren(fragment);
      record.signature = signature;
      if (focusedValue !== null) record.buttons.find(button => button.dataset.choiceValue === focusedValue)?.focus();
    }
    if (record.status) record.status.hidden = select.value !== '';
    const options = new Map([...select.options].map(option => [option.value, option]));
    let tabStop = false;
    for (const button of record.buttons) {
      const option = options.get(button.dataset.choiceValue);
      button.disabled = !option || optionDisabled(option, select);
      const selected = select.value === button.dataset.choiceValue;
      button.setAttribute('aria-checked', String(selected));
      button.tabIndex = selected && !button.disabled ? 0 : -1;
      tabStop ||= button.tabIndex === 0;
    }
    if (!tabStop) {
      const first = record.buttons.find(button => !button.disabled);
      if (first) first.tabIndex = 0;
    }
  }
  function refresh() {
    for (const [select, record] of records) {
      if (!select.isConnected) {
        record.observer.disconnect();
        record.group.remove();
        records.delete(select);
      }
    }
    document.querySelectorAll('select').forEach(install);
    records.forEach(sync);
  }
  function init() {
    refresh();
    const observer = new MutationObserver(records => {
      if (records.some(record => [...record.addedNodes].some(node => node.nodeType === 1 &&
        (node.matches('select') || node.querySelector('select'))))) scheduleRefresh();
    });
    observer.observe(document.body, {subtree:true, childList:true});
  }
  window.PVChoices = {refresh};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
})();
