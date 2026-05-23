# AI Trending Radar

GitHub AI 开源项目每日趋势追踪。

- 数据来源：[GitHub Trending API 镜像](https://github.com/isboyjc/github-trending-api) + GitHub REST API 补充仓库元数据
- 自动更新：GitHub Actions 每天 UTC 12:00（北京时间 20:00）自动抓取并部署
- 页面托管：GitHub Pages

## 本地运行

```bash
# 抓取数据（仅标准库；建议配置 GITHUB_TOKEN 以提高 API 限额）
python3 scripts/fetch_trending.py

# 本地预览（可选，Python 内置 HTTP 服务）
python3 -m http.server 8080
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
