# 离线地理底图

`static/geography.js` 仅保存 Natural Earth(自然地理底图) 1:110m 数据转换得到的陆地轮廓与六个国家概览标签位置，不包含行政边界线或精确厂址。所有市场节点等大，不能解读为销量或风险大小。

来源：https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson

原始下载 SHA256、六个标签位置及下载记录见 `workspace/kimi-research/v3/geography-source.json`。取每个国家几何外环，不绘边界描边，忽略南极；投影为 `x=(longitude+180)*2`、`y=(85-latitude)*2`，保留一位小数。标签位置取原数据 `LABEL_X` / `LABEL_Y`；原数据 177 个要素转换成 280 条路径。轮廓数据只用于概览，不代表业务证据。

Natural Earth 的地理数据为公有领域，可修改与分发：[官方使用条款](https://www.naturalearthdata.com/about/terms-of-use/)。页面运行不请求地图、字体或任何外部图表服务；导出时仅在报告包含市场图时内嵌底图。
