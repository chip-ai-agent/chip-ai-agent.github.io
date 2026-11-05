(() => {
  'use strict';
  for (const root of document.querySelectorAll('.routing-explorer')) {
    const data = JSON.parse(root.querySelector('.routing-chart-data').textContent);
    const zh = root.dataset.language === 'zh';
    const metricSelect = root.querySelector('select');
    const bars = root.querySelector('.explorer-bars');
    const status = root.querySelector('.explorer-status');
    let split = 'D3-A';
    const format = (value, metric) => {
      if (metric === 'cp' || metric === 'rout') return `${(value * 100).toFixed(1)}%`;
      return value.toLocaleString('en-US', { minimumFractionDigits: metric === 'wirelength' ? 1 : 2, maximumFractionDigits: metric === 'wirelength' ? 1 : 2 });
    };
    function render() {
      const metric = metricSelect.value;
      const current = data.splits[split];
      const higher = metric === 'cp' || metric === 'rout';
      const maximum = higher ? 1 : Math.max(...current.methods.map(row => row[metric]));
      const best = (higher ? Math.max : Math.min)(...current.methods.map(row => row[metric]));
      const label = metricSelect.selectedOptions[0].textContent;
      root.querySelector('.explorer-title').textContent = `${split} · ${label}`;
      root.querySelector('.explorer-direction').textContent = higher ? (zh ? '越高越好 ↑' : 'Higher is better ↑') : (zh ? '越低越好 ↓' : 'Lower is better ↓');
      for (const button of root.querySelectorAll('[data-split]')) button.setAttribute('aria-pressed', String(button.dataset.split === split));
      const fragment = document.createDocumentFragment();
      for (const row of current.methods) {
        const item = document.createElement('div');
        item.className = `explorer-bar-row${row.key === 'ours' ? ' is-ours' : ''}`;
        const name = document.createElement('span');
        name.className = 'explorer-method-name';
        name.textContent = row.name;
        const track = document.createElement('span');
        track.className = 'explorer-bar-track';
        const fill = document.createElement('span');
        fill.className = 'explorer-bar-fill';
        fill.style.width = `${maximum ? row[metric] / maximum * 100 : 0}%`;
        track.append(fill);
        const value = document.createElement('span');
        value.className = 'explorer-value';
        value.textContent = format(row[metric], metric);
        if (row[metric] === best) {
          const badge = document.createElement('small');
          badge.className = 'explorer-best';
          badge.textContent = zh ? '最佳' : 'Best';
          value.append(badge);
        }
        item.append(name, track, value);
        fragment.append(item);
      }
      bars.replaceChildren(fragment);
      const descriptions = current.methods.map(row => `${row.name}: ${format(row[metric], metric)}`).join('; ');
      const prefix = `${split} · ${current.boards} ${zh ? '块板' : 'boards'} · ${label}`;
      status.textContent = prefix;
      bars.setAttribute('aria-label', `${prefix}. ${descriptions}`);
    }
    root.querySelector('.explorer-splits').addEventListener('click', event => {
      const button = event.target.closest('button[data-split]');
      if (!button) return;
      split = button.dataset.split;
      render();
    });
    metricSelect.addEventListener('change', render);
    render();
  }
})();
