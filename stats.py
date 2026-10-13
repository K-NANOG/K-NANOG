#!/usr/bin/env python3
"""Render stats.svg: GitHub activity for one account, drawn as a terminal session.

GH_TOKEN reads repositories, commits and languages: a personal token sees the
private ones, the Actions GITHUB_TOKEN only public ones. CAL_TOKEN (default
GH_TOKEN) reads the contribution calendar. Give it the GITHUB_TOKEN: it counts
private contributions the way the public profile graph does, while a
fine-grained token drops those in repositories it cannot read.
Usage:  GH_TOKEN=... [CAL_TOKEN=...] python3 stats.py [login] [out.svg]
Stdlib only, so the workflow needs no install step.
"""
import collections
import datetime as dt
import json
import os
import sys
import urllib.request
from xml.sax.saxutils import escape

LOGIN = sys.argv[1] if len(sys.argv) > 1 else "K-NANOG"
OUT = sys.argv[2] if len(sys.argv) > 2 else "stats.svg"
COLS = 78  # terminal width in characters, as in the loop_score banners


def gql(token, query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        json.dumps({"query": query, "variables": variables}).encode(),
        {"Authorization": f"bearer {token}"},
    )
    body = json.load(urllib.request.urlopen(req))
    if "errors" in body:
        sys.exit(f"graphql: {body['errors']}")
    return body["data"]["user"]


def fetch():
    repo_token = os.environ["GH_TOKEN"]
    cal_token = os.environ.get("CAL_TOKEN") or repo_token
    user = gql(
        repo_token,
        """query($login: String!) { user(login: $login) {
          createdAt
          repositories(ownerAffiliations: OWNER, first: 100) { totalCount nodes {
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
            defaultBranchRef { target { ... on Commit { history { totalCount } } } } } } } }""",
        login=LOGIN,
    )
    user["contributionsCollection"] = gql(
        cal_token,
        """query($login: String!) { user(login: $login) {
          contributionsCollection { contributionCalendar { totalContributions
            weeks { contributionDays { contributionCount date } } } } } }""",
        login=LOGIN,
    )["contributionsCollection"]
    # all-time contributions: the API answers one year at a time
    since = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    alltime = 0
    for year in range(since.year, now.year + 1):
        start = max(since, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
        end = min(now, dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc))
        alltime += gql(
            cal_token,
            """query($login: String!, $from: DateTime!, $to: DateTime!) { user(login: $login) {
              contributionsCollection(from: $from, to: $to) { contributionCalendar { totalContributions } } } }""",
            login=LOGIN, **{"from": start.isoformat(), "to": end.isoformat()},
        )["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    return user, alltime, now


def summarize(user, alltime):
    cal = user["contributionsCollection"]["contributionCalendar"]
    weeks = [[d["contributionCount"] for d in w["contributionDays"]] for w in cal["weeks"]]
    days = [n for w in weeks for n in w]
    best = run = 0
    for n in days:
        run = run + 1 if n else 0
        best = max(best, run)
    # a day with no contribution yet does not break the streak until it is over
    cur = 0
    for n in reversed(days[:-1] if days and not days[-1] else days):
        if not n:
            break
        cur += 1
    langs = collections.Counter()
    commits = 0
    for r in user["repositories"]["nodes"]:
        ref = r["defaultBranchRef"]
        commits += ref["target"]["history"]["totalCount"] if ref else 0
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] += e["size"]
    return dict(
        year=cal["totalContributions"], alltime=alltime, commits=commits,
        repos=user["repositories"]["totalCount"], since=user["createdAt"][:10],
        active=sum(1 for n in days if n), ndays=len(days), cur=cur, best=best,
        weeks=weeks, langs=langs,
    )


def bar(frac, width):
    """[#+++.......]: '#' per whole step, '+' for the remainder, as in the monitors."""
    filled = frac * width
    whole = int(filled)
    part = 1 if filled - whole >= 0.5 and whole < width else 0
    return "[" + "#" * whole + "+" * part + "." * (width - whole - part) + "]"


def lines(s, now):
    hr = "#" * COLS
    row = lambda text="": f"##  {text:<{COLS - 6}}##"
    out = [
        ("prompt", f"[{LOGIN.lower()}@github:~]$ stats --live"),
        ("", hr), ("", row()),
        ("", row(f"{LOGIN}  ::  since {s['since']}  ::  {s['repos']} repositories")),
        ("", row(f"updated   {now:%Y-%m-%dT%H:%MZ}")),
        ("", row()), ("", hr), ("", ""),
        ("", f"  contributions   {s['year']:>6,}  last 365 days   {s['alltime']:>6,}  all time"),
        ("", f"  commits         {s['commits']:>6,}  on default branches"),
        ("", f"  active days     {bar(s['active'] / s['ndays'], 30)}  {s['active']}/{s['ndays']}"
             f"  {s['active'] / s['ndays']:6.1%}"),
        ("", f"  streak          {s['cur']:>6}  days now        {s['best']:>6}  best"),
        ("", ""),
        ("grid", "  contribution grid  ::  one square per day, one column per week"),
    ]
    out += [("gridrow", "")] * 7
    out += [("", "    □ none  ▣ some  ■ high"), ("", "")]
    total = sum(s["langs"].values()) or 1
    for name, size in s["langs"].most_common(6):
        out.append(("", f"  {name:<14}  {bar(size / total, 40)}  {size / total:6.1%}"))
    out += [("", ""), ("cursor", f"[{LOGIN.lower()}@github:~]$ ")]
    return out


def render(s, now):
    fs, cw, lh, pad = 13, 7.8, 18, 20  # font size, character width, line height, padding
    rows = lines(s, now)
    W, H = pad * 2 + COLS * cw, pad * 2 + len(rows) * lh
    fg, dim, bg = "#d0d0d0", "#6e6e6e", "#000"
    css = (
        f"text{{font:{fs}px 'JetBrains Mono','DejaVu Sans Mono',Menlo,Consolas,monospace;"
        f"fill:{fg};white-space:pre}}.d{{fill:{dim}}}"
        ".c{animation:blink 1.1s steps(1) infinite}@keyframes blink{50%{opacity:0}}"
    )
    body, gi = [], 0
    # ■ for the busiest quarter of active days, ▣ for the rest
    active = sorted(n for w in s["weeks"] for n in w if n)
    hi = active[len(active) * 3 // 4] if active else 1
    for i, (kind, text) in enumerate(rows):
        y = pad + (i + 1) * lh - 5
        if kind == "gridrow":
            # bracketed rows of squares, drawn as shapes so they align in any font
            x0 = pad + 2 * cw
            cell = 9.4
            g = [f'<text x="{x0:.1f}" y="{y}">[</text>']
            for wi, week in enumerate(s["weeks"]):
                if gi >= len(week):
                    continue
                n = week[gi]
                x, top = x0 + cw + 1 + wi * cell, y - 9.5
                if n >= hi:
                    g.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="8" height="8" fill="{fg}"/>')
                else:
                    g.append(f'<rect x="{x + .5:.1f}" y="{top + .5:.1f}" width="7" height="7" '
                             f'fill="none" stroke="{fg if n else dim}" stroke-width="1"/>')
                    if n:
                        g.append(f'<rect x="{x + 2.5:.1f}" y="{top + 2.5:.1f}" width="3" height="3" fill="{fg}"/>')
            xr = x0 + cw + 1 + len(s["weeks"]) * cell
            g.append(f'<text x="{xr:.1f}" y="{y}">]</text>')
            g.append(f'<text x="{xr + 2 * cw:.1f}" y="{y}" class="d">{"MTWTFSS"[(gi + 6) % 7]}</text>')
            gi += 1
            body.append(f'<g>{"".join(g)}</g>')
            continue
        if not text:
            continue
        extra = ""
        if kind == "cursor":
            extra = (f'<rect class="c" x="{pad + len(text) * cw:.1f}" y="{y - 11}" '
                     f'width="{cw:.1f}" height="14" fill="{fg}"/>')
        body.append(
            f'<g><text x="{pad}" y="{y}" '
            f'textLength="{len(text) * cw:.1f}" lengthAdjust="spacingAndGlyphs">{escape(text)}</text>{extra}</g>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" viewBox="0 0 {W:.0f} {H}" width="{W:.0f}" height="{H}">'
        f"<style>{css}</style><rect width=\"100%\" height=\"100%\" rx=\"6\" fill=\"{bg}\"/>"
        + "\n" + "\n".join(body) + "\n</svg>\n"
    )


if __name__ == "__main__":
    user, alltime, now = fetch()
    with open(OUT, "w") as f:
        f.write(render(summarize(user, alltime), now))
