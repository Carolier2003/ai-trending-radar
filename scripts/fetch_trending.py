"""
GitHub AI Trending Radar — Data Fetcher v2

Pulls trending repos from isboyjc/github-trending-api (which scrapes
github.com/trending daily), filters for AI/LLM/agent related projects,
and enriches topics via GitHub REST API.

Zero cache. Growth data (`addStars`) comes directly from GitHub Trending.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, UTC
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data.json"
TODAY = datetime.now(UTC).strftime("%Y-%m-%d")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ── Data sources (free, no auth needed) ─────────────────
TRENDING_BASE = "https://raw.githubusercontent.com/isboyjc/github-trending-api/main/data"
SOURCES = [
    f"{TRENDING_BASE}/weekly/all.json",
    f"{TRENDING_BASE}/monthly/all.json",
    f"{TRENDING_BASE}/weekly/python.json",
    f"{TRENDING_BASE}/weekly/typescript.json",
    f"{TRENDING_BASE}/weekly/rust.json",
]

# ── AI relevance filters ───────────────────────────────
AI_KEYWORDS = [
    "llm", "agent", "ai.", "gpt", "claude", "openai", "transformer",
    "neural", "embedding", "llama", "mistral", "diffusion", "langchain",
    "prompt", "rag", "mcp", "copilot", "deepseek", "qwen", "vllm",
    "chatbot", "open-source ai", "slm", "fine-tun", "inference",
    "multi-agent", "agentic", "autogen", "text-to-", "image-gen",
    "stable diffusion", "coder agent", "skills framework",
]
# Repos to always include (well-known AI projects)
ALWAYS_INCLUDE = {
    "ollama/ollama", "huggingface/transformers", "langgenius/dify",
    "langchain-ai/langchain", "open-webui/open-webui", "nomic-ai/gpt4all",
    "vllm-project/vllm", "browser-use/browser-use",
}
# Repos to always exclude (not AI despite keyword match)
ALWAYS_EXCLUDE = {
    "oven-sh/bun",  # JS runtime, not AI
}


def is_ai_relevant(name: str, desc: str) -> bool:
    """Check if repo is AI/LLM/agent related by name + description."""
    if name in ALWAYS_INCLUDE:
        return True
    if name in ALWAYS_EXCLUDE:
        return False
    text = (name + " " + desc).lower()
    return any(kw in text for kw in AI_KEYWORDS)


# ── GitHub API helpers ──────────────────────────────────

def github_api(path: str, params: dict = None):
    """GET GitHub REST API. Returns (data | None, rate_remaining)."""
    url = f"https://api.github.com{path}"
    if params:
        url += "?" + urlencode(params, doseq=True)
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-trending-radar/2.0",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                remaining = resp.headers.get("X-RateLimit-Remaining", "0")
                data = json.loads(resp.read().decode())
                return data, int(remaining) if remaining.isdigit() else 0
        except urllib.error.HTTPError as e:
            if e.code == 403:
                reset = int((e.headers or {}).get("X-RateLimit-Reset", 0))
                wait = max(reset - time.time(), 0) + 5
                if 0 < wait < 120:
                    print(f"  Rate-limited, waiting {wait:.0f}s ...", file=sys.stderr)
                    time.sleep(wait)
                    continue
            if attempt < 2:
                time.sleep(1)
                continue
            print(f"  HTTP {e.code} on {url}", file=sys.stderr)
            return None, -1
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            print(f"  Error on {url}: {e}", file=sys.stderr)
            return None, -1
    return None, -1


def get_repo_extra(full_name: str) -> dict:
    """Get authoritative repo metadata from GitHub."""
    data, _ = github_api(f"/repos/{full_name}")
    if not data:
        return {}
    return {
        "forks": data.get("forks_count", 0),
        "last_commit": (data.get("pushed_at") or "")[:10],
        "language": data.get("language") or "Other",
        "topics": data.get("topics", []),
        "total_stars": data.get("stargazers_count", 0),
    }


# ── Trend classifier ────────────────────────────────────

def classify(repo: dict) -> tuple[str, str]:
    s7 = repo.get("stars_7d", 0)
    total = repo.get("total_stars", 0)
    # Surging: weekly growth >= 10000 (top of GitHub Trending)
    if s7 >= 10000:
        return "🔥 本周飙升", "surging"
    # Classic: established heavyweights (>=50k stars) with moderate growth
    if total >= 50000:
        return "⭐ 经典热门", "classic"
    # New star: small project (<20k stars) gaining traction
    if total < 20000 and s7 >= 100:
        return "🌱 活跃新星", "newstar"
    # Rising: everything else with momentum
    if s7 >= 100:
        return "📈 稳步上升", "rising"
    return "📈 稳步上升", "rising"


# ── Main ────────────────────────────────────────────────

def fetch_trending_json(url: str) -> list[dict]:
    """Fetch a single trending JSON endpoint."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-trending-radar/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data.get("items", [])
    except Exception as e:
        print(f"  Failed to fetch {url}: {e}", file=sys.stderr)
        return []


def parse_int(s: str) -> int:
    """Parse '16,288' -> 16288."""
    if isinstance(s, int):
        return s
    return int(str(s).replace(",", "")) if s else 0


def main():
    print(f"=== GitHub AI Trending Radar · {TODAY} ===\n")

    # Phase 1: Pull trending data from all sources
    seen = set()
    raw_repos = []

    for url in SOURCES:
        source_name = url.split("/")[-1].replace(".json", "")
        print(f"Fetching: {source_name}")
        items = fetch_trending_json(url)
        for item in items:
            name = item.get("title", "")
            if not name or name in seen:
                continue
            if not is_ai_relevant(name, item.get("description", "")):
                continue
            seen.add(name)
            raw_repos.append(item)
        time.sleep(0.3)

    print(f"\nAI-relevant repos: {len(raw_repos)}")

    # Phase 2: Enrich with GitHub API (topics, stars, language)
    enriched = []
    for i, r in enumerate(raw_repos):
        name = r["title"]
        add_stars = parse_int(r.get("addStars", "0"))
        total_stars = parse_int(r.get("stars", "0"))
        forks = parse_int(r.get("forks", "0"))

        extra = get_repo_extra(name)
        if (i + 1) % 5 == 0:
            print(f"  enriched {i+1}/{len(raw_repos)} ...")
        time.sleep(0.5)

        enriched.append({
            "name": name,
            "description": (r.get("description") or "").replace("\n", " ").strip(),
            "total_stars": extra.get("total_stars") or total_stars,
            "stars_7d": add_stars,
            "stars_30d": 0,  # will fill from monthly data later
            "stars_30d_estimated": False,
            "forks": extra.get("forks") or forks,
            "last_commit": extra.get("last_commit", ""),
            "language": extra.get("language") or r.get("language") or "Other",
            "topics": extra.get("topics", [])[:8],
            "url": r.get("url", f"https://github.com/{name}"),
        })

    # Phase 3: Build monthly growth map from all available monthly sources
    MONTHLY_SOURCES = [
        f"{TRENDING_BASE}/monthly/all.json",
        f"{TRENDING_BASE}/monthly/python.json",
        f"{TRENDING_BASE}/monthly/typescript.json",
        f"{TRENDING_BASE}/monthly/rust.json",
        f"{TRENDING_BASE}/monthly/javascript.json",
        f"{TRENDING_BASE}/monthly/go.json",
        f"{TRENDING_BASE}/monthly/java.json",
        f"{TRENDING_BASE}/monthly/c++.json",
        f"{TRENDING_BASE}/monthly/swift.json",
    ]
    monthly_map = {}
    for url in MONTHLY_SOURCES:
        for item in fetch_trending_json(url):
            name = item.get("title", "")
            if name and name not in monthly_map:
                monthly_map[name] = parse_int(item.get("addStars", "0"))

    print(f"Monthly growth data available for: {len(monthly_map)} repos")

    for repo in enriched:
        if repo["name"] in monthly_map:
            repo["stars_30d"] = monthly_map[repo["name"]]
            repo["stars_30d_estimated"] = False
        else:
            # Estimate monthly growth from weekly (assume 4 weeks)
            repo["stars_30d"] = repo["stars_7d"] * 4
            repo["stars_30d_estimated"] = True

    # Assign tags
    for repo in enriched:
        tag, tag_class = classify(repo)
        repo["tag"] = tag
        repo["tag_class"] = tag_class

    # Sort: weekly growth desc
    enriched.sort(key=lambda x: x["stars_7d"], reverse=True)

    # Keep top 20
    final = enriched[:20]

    if not final:
        print("\nERROR: No AI repos found in trending data.", file=sys.stderr)
        print("Keeping existing data.json unchanged.", file=sys.stderr)
        sys.exit(1)

    classic = sum(1 for r in final if r["tag_class"] == "classic")
    surging = sum(1 for r in final if r["tag_class"] == "surging")
    rising = sum(1 for r in final if r["tag_class"] == "rising")
    newstar = sum(1 for r in final if r["tag_class"] == "newstar")

    print(f"\nFinal: {len(final)} projects")
    print(f"  ⭐ 经典热门: {classic}  |  🔥 本周飙升: {surging}  |  📈 稳步上升: {rising}  |  🌱 活跃新星: {newstar}")

    DATA_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n")
    print(f"\nWritten: {DATA_FILE}")

    print("\n── Top by weekly growth ──")
    for r in final[:5]:
        print(f"  {r['name']}  ★{r['total_stars']:,}  +{r['stars_7d']:,}/wk  +{r['stars_30d']:,}/mo")


if __name__ == "__main__":
    main()
