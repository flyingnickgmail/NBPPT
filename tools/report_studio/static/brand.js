/* Shared report palette. Keep chart, CSS and spatial renderers on one warm system. */
window.ReportBrand = (() => {
  const freeze = value => Object.freeze(value);
  const light = freeze({
    paper: '#F6F5F1',
    surface: '#FFFDF9',
    ink: '#242522',
    muted: '#68645D',
    line: '#D5CFC5',
    soft: '#EDE8DF',
    accent: '#A34F2D',
    negative: '#A53D32'
  });
  const dark = freeze({
    paper: '#1B1A18',
    surface: '#24221F',
    ink: '#F6F5F1',
    muted: '#C8C1B7',
    line: '#514B43',
    soft: '#302D29',
    accent: '#E6A07E',
    negative: '#F09A8B'
  });
  const tones = freeze({
    ink: freeze([36, 37, 34]),
    accent: freeze([163, 79, 45]),
    silver: freeze([148, 143, 134]),
    chalk: freeze([246, 245, 241]),
    copper: freeze([163, 79, 45])
  });
  const nightTones = freeze({ink: freeze([162,157,147]), accent: freeze([200,131,98]), silver: freeze([177,172,165]), chalk: freeze([221,215,204]), copper: freeze([200,131,98])});
  const chartColors = freeze(['var(--accent)', 'var(--ink)', 'var(--muted)', '#C98261', '#A99E90']);
  const apply = (root, night = false) => Object.entries(night ? dark : light).forEach(([key, value]) => root.style.setProperty('--' + key, value));
  return freeze({wordmark: '友车科技 / 研究报告', light, dark, tones, nightTones, chartColors, apply});
})();
