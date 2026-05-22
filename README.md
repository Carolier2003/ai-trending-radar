# AI Trending Radar

GitHub AI 开源项目每日趋势追踪。

- 数据来源：[GitHub Search API](https://docs.github.com/en/rest/reference/search)
- 自动更新：GitHub Actions 每天 UTC 8:00 自动抓取并部署
- 页面托管：GitHub Pages

## 本地运行

```bash
# 安装依赖（仅标准库）
pip install --upgrade pip

# 抓取数据
python scripts/fetch_trending.py

# 本地预览（可选，Python 内置 HTTP 服务）
python -m http.server 8080
# 然后打开 http://localhost:8080
```

## 项目结构

```
.
├── index.html              # 前端页面（从 data.json 动态加载）
├── data.json               # 项目数据（由脚本生成）
├── scripts/
│   └── fetch_trending.py   # 数据抓取脚本
└── .github/workflows/
    └── deploy.yml          # GitHub Actions 自动部署
```