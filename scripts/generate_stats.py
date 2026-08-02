"""
Pulls commit/activity data for a GitHub user and renders a custom
terminal-style stats card as SVG (dark + light variants).

Env vars:
    GH_TOKEN or GITHUB_TOKEN   - token with public read access (required)
    GH_USERNAME                - profile to render stats for (default below)
"""

import datetime as dt
import os
import sys
from collections import Counter

import requests

USERNAME = os.environ.get("GH_USERNAME", "yashbedekar07")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
API_GRAPHQL = "https://api.github.com/graphql"
API_REST = "https://api.github.com"

if not TOKEN:
    sys.exit("Missing GH_TOKEN / GITHUB_TOKEN environment variable")

HEADERS_GRAPHQL = {"Authorization": f"bearer {TOKEN}"}
HEADERS_REST = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github+json",
}

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      nodes {
        stargazerCount
        languages(first: 5, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
}
"""


def fetch_graphql():
    resp = requests.post(
        API_GRAPHQL,
        json={"query": GRAPHQL_QUERY, "variables": {"login": USERNAME}},
        headers=HEADERS_GRAPHQL,
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        sys.exit(f"GraphQL errors: {payload['errors']}")
    return payload["data"]["user"]


def fetch_recent_push_hours():
    """Hour-of-day (UTC) for recent push events, used for the mood indicator."""
    hours = []
    for page in (1, 2):
        resp = requests.get(
            f"{API_REST}/users/{USERNAME}/events/public",
            params={"per_page": 100, "page": page},
            headers=HEADERS_REST,
            timeout=30,
        )
        if resp.status_code != 200:
            break
        events = resp.json()
        if not events:
            break
        for event in events:
            if event.get("type") == "PushEvent":
                created = event.get("created_at")
                if created:
                    hours.append(
                        dt.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").hour
                    )
    return hours


def compute_streak(weeks):
    days = []
    for week in weeks:
        for day in week["contributionDays"]:
            days.append(
                (dt.date.fromisoformat(day["date"]), day["contributionCount"])
            )
    days.sort(key=lambda d: d[0])

    today = dt.date.today()
    by_date = {d: c for d, c in days}

    streak = 0
    cursor = today
    # allow today to be empty (day not over yet) without breaking the streak
    if by_date.get(today, 0) == 0:
        cursor = today - dt.timedelta(days=1)
    while by_date.get(cursor, 0) > 0:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def compute_top_languages(repo_nodes, limit=4):
    totals = Counter()
    colors = {}
    for repo in repo_nodes:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            totals[name] += edge["size"]
            colors[name] = edge["node"]["color"] or "#999999"

    total_size = sum(totals.values()) or 1
    top = totals.most_common(limit)
    return [
        {"name": name, "pct": round(size * 100 / total_size), "color": colors[name]}
        for name, size in top
    ]


def compute_mood(hours):
    if not hours:
        return "unknown", "No recent public push activity"

    def bucket(h):
        if 22 <= h or h < 5:
            return "night_owl"
        if 5 <= h < 10:
            return "early_bird"
        if 10 <= h < 18:
            return "daytime_coder"
        return "evening_coder"

    counts = Counter(bucket(h) for h in hours)
    mood, _ = counts.most_common(1)[0]

    labels = {
        "night_owl": ("Night Owl", "most commits land after 10pm"),
        "early_bird": ("Early Bird", "most commits land 5am-10am"),
        "daytime_coder": ("Daytime Coder", "most commits land 10am-6pm"),
        "evening_coder": ("Evening Coder", "most commits land 6pm-10pm"),
    }
    return labels[mood]


THEMES = {
    "dark": {
        "bg": "#0d1117",
        "titlebar": "#161b22",
        "border": "#30363d",
        "text": "#c9d1d9",
        "muted": "#6e7681",
        "accent": "#58a6ff",
        "prompt": "#3fb950",
        "track": "#21262d",
    },
    "light": {
        "bg": "#ffffff",
        "titlebar": "#f6f8fa",
        "border": "#d0d7de",
        "text": "#24292f",
        "muted": "#57606a",
        "accent": "#0969da",
        "prompt": "#1a7f37",
        "track": "#eaeef2",
    },
}

WIDTH = 480


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_svg(theme_name, stats):
    t = THEMES[theme_name]

    fire = "\U0001F525" if stats["streak"] else ""
    day_word = "day" if stats["streak"] == 1 else "days"
    stat_lines = [
        f'commits (1y).... {stats["commits"]}',
        f'stars........... {stats["stars"]}',
        f'followers....... {stats["followers"]}',
        f'streak.......... {stats["streak"]} {day_word} {fire}',
    ]

    svg_parts = []

    svg_parts.append(f'<text x="24" y="52" fill="{t["prompt"]}" font-family="monospace" font-size="13">$</text>')
    svg_parts.append(f'<text x="40" y="52" fill="{t["muted"]}" font-family="monospace" font-size="13">whoami</text>')
    svg_parts.append(f'<text x="24" y="72" fill="{t["accent"]}" font-family="monospace" font-size="15" font-weight="bold">{esc(stats["username"])}</text>')

    y = 100
    svg_parts.append(f'<text x="24" y="{y}" fill="{t["prompt"]}" font-family="monospace" font-size="13">$</text>')
    svg_parts.append(f'<text x="40" y="{y}" fill="{t["muted"]}" font-family="monospace" font-size="13">git log --stat --since="1 year ago"</text>')
    for i, line in enumerate(stat_lines):
        yy = y + 22 * (i + 1)
        svg_parts.append(f'<text x="40" y="{yy}" fill="{t["text"]}" font-family="monospace" font-size="13" xml:space="preserve">{esc(line)}</text>')

    y2 = y + 22 * (len(stat_lines) + 1) + 12
    svg_parts.append(f'<text x="24" y="{y2}" fill="{t["prompt"]}" font-family="monospace" font-size="13">$</text>')
    svg_parts.append(f'<text x="40" y="{y2}" fill="{t["muted"]}" font-family="monospace" font-size="13">top languages</text>')

    bar_x = 130
    bar_w = 220
    for i, lang in enumerate(stats["languages"]):
        yy = y2 + 22 * (i + 1)
        svg_parts.append(f'<text x="40" y="{yy + 6}" fill="{t["text"]}" font-family="monospace" font-size="12">{esc(lang["name"])}</text>')
        svg_parts.append(
            f'<rect x="{bar_x}" y="{yy - 2}" width="{bar_w}" height="8" rx="4" fill="{t["track"]}"/>'
        )
        filled = max(2, round(bar_w * lang["pct"] / 100))
        svg_parts.append(
            f'<rect x="{bar_x}" y="{yy - 2}" width="{filled}" height="8" rx="4" fill="{lang["color"]}"/>'
        )
        svg_parts.append(f'<text x="{bar_x + bar_w + 10}" y="{yy + 6}" fill="{t["muted"]}" font-family="monospace" font-size="12">{lang["pct"]}%</text>')

    y3 = y2 + 22 * (len(stats["languages"]) + 1) + 12
    svg_parts.append(f'<text x="24" y="{y3}" fill="{t["prompt"]}" font-family="monospace" font-size="13">$</text>')
    svg_parts.append(f'<text x="40" y="{y3}" fill="{t["muted"]}" font-family="monospace" font-size="13">mood</text>')
    mood_label, mood_desc = stats["mood"]
    mood_icons = {
        "Night Owl": "\U0001F319",
        "Early Bird": "\U0001F305",
        "Daytime Coder": "☀️",
        "Evening Coder": "\U0001F307",
        "unknown": "❓",
    }
    icon = mood_icons.get(mood_label, "")
    mood_y = y3 + 22
    svg_parts.append(
        f'<text x="40" y="{mood_y}" fill="{t["text"]}" font-family="monospace" font-size="13" xml:space="preserve">{icon} {esc(mood_label)} — {esc(mood_desc)}</text>'
    )

    cursor_y = mood_y + 22
    svg_parts.append(f'<text x="24" y="{cursor_y}" fill="{t["prompt"]}" font-family="monospace" font-size="13">$</text>')
    svg_parts.append(
        f'<rect x="40" y="{cursor_y - 11}" width="8" height="14" fill="{t["accent"]}">'
        f'<animate attributeName="opacity" values="1;0;1" dur="1.2s" repeatCount="indefinite"/>'
        f'</rect>'
    )

    height = cursor_y + 24

    header = [
        f'<svg width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub stats for {esc(stats["username"])}">',
        f'<rect width="{WIDTH}" height="{height}" rx="12" fill="{t["bg"]}" stroke="{t["border"]}"/>',
        f'<rect width="{WIDTH}" height="32" rx="12" fill="{t["titlebar"]}"/>',
        f'<rect y="20" width="{WIDTH}" height="12" fill="{t["titlebar"]}"/>',
        '<circle cx="20" cy="16" r="5" fill="#ff5f56"/>',
        '<circle cx="38" cy="16" r="5" fill="#ffbd2e"/>',
        '<circle cx="56" cy="16" r="5" fill="#27c93f"/>',
        f'<text x="{WIDTH/2}" y="20" text-anchor="middle" fill="{t["muted"]}" '
        f'font-family="monospace" font-size="12">{esc(stats["username"])} - stats.sh</text>',
    ]

    return "\n".join(header + svg_parts + ["</svg>"])


def main():
    user = fetch_graphql()
    calendar = user["contributionsCollection"]["contributionCalendar"]
    hours = fetch_recent_push_hours()

    stats = {
        "username": USERNAME,
        "commits": calendar["totalContributions"],
        "stars": sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        "followers": user["followers"]["totalCount"],
        "streak": compute_streak(calendar["weeks"]),
        "languages": compute_top_languages(user["repositories"]["nodes"]),
        "mood": compute_mood(hours),
    }

    os.makedirs("assets", exist_ok=True)
    for theme in ("dark", "light"):
        svg = render_svg(theme, stats)
        with open(f"assets/stats-{theme}.svg", "w", encoding="utf-8") as f:
            f.write(svg)

    print(f"Generated stats for {USERNAME}: {stats['commits']} commits, "
          f"{stats['streak']}-day streak, mood={stats['mood'][0]}")


if __name__ == "__main__":
    main()
