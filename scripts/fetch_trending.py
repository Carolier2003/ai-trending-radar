#!/usr/bin/env python3
"""
GitHub AI Trending Radar — Data Fetcher

Queries GitHub Search API for top AI/LLM/agent repos, enriches with
star growth from a local cache, and writes data.json at repo root.

Usage:
    python scripts/fetch_trending.py

Env vars (optional):
    GITHUB_TOKEN — personal access token to raise rate limit (60→5000 req/hr)
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data.json"
CACHE_FILE = ROOT / ".star_cache.json"
TODAY = datetime.utcnow().strftime("%Y-%m-%d")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ── Queries ─────────────────────────────────────────────
# Each (query, qualifier) pair; qualifier appends sort/order etc.
AI_QUERIES = [
    # Broad keyword searches instead of restrictive topic: filters
    ("llm agent stars:>1000", "stars"),
    ("ai coding agent claude stars:>1000", "stars"),
    ("open source llm stars:>5000", "stars"),
    ("rag ai stars:>1000", "stars"),
    ("deepseek qwen llm stars:>1000", "stars"),
    ("ai agent framework stars:>2000", "stars"),
    # New / fast-growing repos
    ("ai agent created:>2025-06-01 stars:>500", "stars"),
]

# Repos we explicitly ignore (too generic / not AI-trending news)
IGNORE_REPOS = {
    "tensorflow/tensorflow",
    "pytorch/pytorch",
    "keras-team/keras",
    "scikit-learn/scikit-learn",
    "numpy/numpy",
    "pandas-dev/pandas",
    "microsoft/vscode",
}

# ── API helpers ─────────────────────────────────────────

def github_api(path, params=None):
    """GET GitHub REST API. Returns (data | None, rate_remaining)."""
    url = f"https://api.github.com{path}"
    if params:
        url += "?" + urlencode(params, doseq=True)

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-trending-radar/1.0",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=25) as resp:
            remaining = resp.headers.get("X-RateLimit-Remaining", "0")
            data = json.loads(resp.read().decode())
            return data, int(remaining) if remaining.isdigit() else 0
    except HTTPError as e:
        if e.code == 403:
            reset = int((e.headers or {}).get("X-RateLimit-Reset", 0))
            wait = max(reset - time.time(), 0) + 5
            if wait > 0 and wait < 120:
                print(f"  Rate-limited, waiting {wait:.0f}s ...", file=sys.stderr)
                time.sleep(wait)
                return github_api(path, params)
        print(f"  HTTP {e.code} on {url}", file=sys.stderr)
        return None, -1
    except URLError as e:
        print(f"  Network error: {e}", file=sys.stderr)
        return None, -1


def search_repos(query, sort="stars", per_page=20):
    """Search repos, return list of repo dicts."""
    q = f"{query} archived:false"
    params = {"q": q, "sort": sort, "order": "desc", "per_page": per_page}
    data, _ = github_api("/search/repositories", params)
    if data and "items" in data:
        return data["items"]
    return []


def get_repo_extra(full_name):
    """Get community profile & recent commits for a single repo."""
    repo, _ = github_api(f"/repos/{full_name}")
    if not repo:
        return {}
    return {
        "forks": repo.get("forks_count", 0),
        "last_commit": (repo.get("pushed_at") or "")[:10],
        "language": repo.get("language") or "Other",
        "topics": repo.get("topics", []),
    }


def get_commit_activity(full_name):
    """Get commit activity in past 7 days."""
    stats, _ = github_api(f"/repos/{full_name}/stats/commit_activity")
    if not stats or not isinstance(stats, list):
        return 0
    # stats[-1] is the most recent week
    recent = stats[-1] if stats else {}
    return recent.get("total", 0)


# ── Cache & growth ──────────────────────────────────────

def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def compute_growth(repo_name, current_stars, cache):
    """Record today's snapshot, compute 7d/30d growth from cache.

    Uses the closest available data point within a reasonable window,
    so that growth estimates appear even with partially accumulated cache.
    """
    now = datetime.utcnow()
    history = cache.get(repo_name, {})
    # Only update if not already recorded today
    if TODAY not in history:
        history[TODAY] = current_stars

    # Find closest historical points
    best_7d = (None, 999)
    best_30d = (None, 999)
    for date_str, val in history.items():
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        delta = (now - dt).days
        if 3 <= delta <= 14:
            dist = abs(delta - 7)
            if dist < best_7d[1]:
                best_7d = (val, dist)
        if 14 <= delta <= 50:
            dist = abs(delta - 30)
            if dist < best_30d[1]:
                best_30d = (val, dist)

    stars_7d = max(0, current_stars - best_7d[0]) if best_7d[0] is not None else 0
    stars_30d = max(0, current_stars - best_30d[0]) if best_30d[0] is not None else 0

    cache[repo_name] = history
    return stars_7d, stars_30d


# ── Trend classifier ────────────────────────────────────

def classify(repo):
    """Assign trend tag + CSS class."""
    s7 = repo.get("stars_7d", 0)
    s30 = repo.get("stars_30d", 0)
    total = repo.get("total_stars", 0)

    # 周增超过 200 星就算飙升
    if s7 >= 200:
        return "🔥 本周飙升", "surging"
    # 周增 50-199 星算稳步上升
    if s7 >= 50:
        return "📈 稳步上升", "rising"
    # 总星数 < 2 万且周增 > 20 算新星
    if total < 20000 and s7 >= 20:
        return "🌱 活跃新星", "newstar"
    # 总星数 > 5 万且增长不明显算经典
    if total >= 50000:
        return "⭐ 经典热门", "classic"
    # 默认稳步上升
    return "📈 稳步上升", "rising"


# ── Main ────────────────────────────────────────────────

def main():
    print(f"=== GitHub AI Trending Radar · {TODAY} ===\n")

    cache = load_cache()
    seen = set()
    repos_raw = []

    # Phase 1: search
    for query, sort in AI_QUERIES:
        print(f"Searching: {query} (sort={sort})")
        items = search_repos(query, sort=sort, per_page=12)
        for r in items:
            name = r["full_name"]
            if name in seen or name in IGNORE_REPOS:
                continue
            seen.add(name)
            repos_raw.append(r)
        time.sleep(1.2)  # be gentle with API

    print(f"\nCollected {len(repos_raw)} unique repos.")

    # Phase 2: enrich & rank
    enriched = []
    for i, r in enumerate(repos_raw):
        name = r["full_name"]
        total = r["stargazers_count"]
        s7, s30 = compute_growth(name, total, cache)

        # Quick extra fetch for forks/language/topics/last_commit
        extra = get_repo_extra(name)

        enriched.append({
            "name": name,
            "description": (r.get("description") or "").replace("\n", " ").strip(),
            "total_stars": total,
            "stars_7d": s7,
            "stars_30d": s30,
            "forks": extra.get("forks", r.get("forks_count", 0)),
            "last_commit": extra.get("last_commit", ""),
            "language": extra.get("language", r.get("language") or "Other"),
            "topics": [t for t in extra.get("topics", r.get("topics", [])) if t != "llm"][:8],
            "url": r["html_url"],
        })

        if (i + 1) % 5 == 0:
            print(f"  enriched {i+1}/{len(repos_raw)} ...")

    # Assign tags
    for repo in enriched:
        tag, tag_class = classify(repo)
        repo["tag"] = tag
        repo["tag_class"] = tag_class

    # Sort: total stars desc
    enriched.sort(key=lambda x: x["total_stars"], reverse=True)

    # Keep top 18-20, ensuring diversity
    final = enriched[:20]

    if not final:
        print("\nERROR: No repos collected. Possible API rate limit or network issue.", file=sys.stderr)
        print("Keeping existing data.json unchanged.", file=sys.stderr)
        sys.exit(1)

    # Stats
    classic = sum(1 for r in final if r["tag_class"] == "classic")
    surging = sum(1 for r in final if r["tag_class"] == "surging")
    rising = sum(1 for r in final if r["tag_class"] == "rising")
    newstar = sum(1 for r in final if r["tag_class"] == "newstar")

    print(f"\nFinal: {len(final)} projects")
    print(f"  ⭐ 经典热门: {classic}  |  🔥 本周飙升: {surging}  |  📈 稳步上升: {rising}  |  🌱 活跃新星: {newstar}")

    # Write
    DATA_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n")
    print(f"\nWritten: {DATA_FILE}")

    save_cache(cache)

    # Summary
    print("\n── Top by total stars ──")
    for r in final[:3]:
        print(f"  {r['name']}  ★{r['total_stars']:,}  (+{r['stars_7d']:,}w / +{r['stars_30d']:,}m)")
    print("\n── Top by 7d growth ──")
    by_growth = sorted(final, key=lambda x: x["stars_7d"], reverse=True)
    for r in by_growth[:3]:
        print(f"  {r['name']}  +{r['stars_7d']:,} ⭐ this week")


if __name__ == "__main__":
    main()