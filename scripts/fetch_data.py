#!/usr/bin/env python3
"""Fetch contribution calendar + public repo stats into data/github.json.

Run by the daily GitHub Action. Needs GITHUB_TOKEN (the Action's built-in token
covers public contributions; set a CARDS_TOKEN secret with a classic PAT
(read:user) if you also want private contributions counted).
"""
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "cards.config.json").read_text())
OUT = ROOT / "data" / "github.json"

QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC,
                 isFork: false, orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name description url stargazerCount forkCount pushedAt
        primaryLanguage { name color }
        repositoryTopics(first: 8) { nodes { topic { name } } }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 1
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": CONFIG["login"]}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        print(json.dumps(payload["errors"], indent=2), file=sys.stderr)
        return 1

    u = payload["data"]["user"]
    repos = []
    # don't count the profile repo itself (e.g. CoderHaste/CoderHaste)
    self_repo = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1].lower()
    for n in u["repositories"]["nodes"]:
        if n["name"].lower() in {self_repo, CONFIG["login"].lower()}:
            continue
        lang = n["primaryLanguage"] or {}
        repos.append({
            "name": n["name"],
            "description": n["description"] or "",
            "url": n["url"],
            "stars": n["stargazerCount"],
            "forks": n["forkCount"],
            "pushed_at": n["pushedAt"],
            "language": lang.get("name"),
            "language_color": lang.get("color"),
            "topics": [t["topic"]["name"] for t in n["repositoryTopics"]["nodes"]],
        })

    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [
        {"date": d["date"], "count": d["contributionCount"]}
        for w in cal["weeks"] for d in w["contributionDays"]
    ]

    data = {
        "sample": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user": {
            "login": CONFIG["login"],
            "name": u["name"],
            "followers": u["followers"]["totalCount"],
            "public_repos": len(repos),
            "stars": sum(r["stars"] for r in repos),
            "language_counts": dict(Counter(r["language"] for r in repos if r["language"])),
        },
        "total_contributions": cal["totalContributions"],
        "calendar": days,
        "repos": repos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(days)} days, {len(repos)} repos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
