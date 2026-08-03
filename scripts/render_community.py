#!/usr/bin/env python3
"""Render guestbook notes and recent discussion threads into README.md.

Only comments the repo owner has reacted to with a thumbs up are published.
Anyone can post in the guestbook, so an explicit approval reaction is the gate
that keeps unreviewed text off the profile page.
"""
import html
import json
import os
import re
import sys
import urllib.request

OWNER = os.environ.get("GH_OWNER", "acharyabi")
REPO = os.environ.get("GH_REPO", "acharyabi")
GUESTBOOK = int(os.environ.get("GUESTBOOK_NUMBER", "3"))
MAX_NOTES = 5
MAX_THREADS = 5
MAX_LEN = 240

QUERY = """
query($owner:String!, $repo:String!, $number:Int!) {
  repository(owner:$owner, name:$repo) {
    discussion(number:$number) {
      comments(last:100) {
        nodes {
          bodyText
          url
          createdAt
          author { login url }
          reactionGroups {
            content
            reactors(first:100) { nodes { ... on User { login } } }
          }
        }
      }
    }
    discussions(first:20, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes {
        number title url createdAt
        author { login }
        category { name }
        comments { totalCount }
      }
    }
  }
}
"""


def gql(token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({
            "query": QUERY,
            "variables": {"owner": OWNER, "repo": REPO, "number": GUESTBOOK},
        }).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-community-renderer",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        sys.exit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["repository"]


def approved(comment):
    """True when the profile owner gave the comment a thumbs up."""
    for group in comment.get("reactionGroups") or []:
        if group["content"] != "THUMBS_UP":
            continue
        for node in group["reactors"]["nodes"]:
            if node and node.get("login") == OWNER:
                return True
    return False


def clean(text):
    """bodyText is already markdown-stripped; flatten and bound it anyway."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN].rsplit(" ", 1)[0] + "..."
    return html.escape(text, quote=False)


def render_notes(discussion):
    if not discussion:
        return "_Guestbook thread not found._"

    notes = [c for c in discussion["comments"]["nodes"]
             if approved(c) and (c.get("author") or {}).get("login")]
    if not notes:
        return ("_No notes yet._ "
                f"[Be the first]({guestbook_url()}).")

    lines = []
    for c in notes[-MAX_NOTES:][::-1]:
        who = c["author"]["login"]
        body = clean(c["bodyText"])
        if not body:
            continue
        lines.append(
            f'> {body}\n>\n> — [@{who}]({c["author"]["url"]}) '
            f'· [link]({c["url"]})'
        )
    return "\n\n".join(lines) if lines else "_No notes yet._"


def render_threads(discussions):
    rows = [d for d in discussions["nodes"] if d["number"] != GUESTBOOK]
    if not rows:
        return "_No threads open yet._"

    out = ["| Thread | Category | Replies |", "|---|---|---|"]
    for d in rows[:MAX_THREADS]:
        who = (d.get("author") or {}).get("login", "ghost")
        title = html.escape(d["title"], quote=False)
        out.append(
            f'| [{title}]({d["url"]}) by @{who} '
            f'| {d["category"]["name"]} | {d["comments"]["totalCount"]} |'
        )
    return "\n".join(out)


def guestbook_url():
    return f"https://github.com/{OWNER}/{REPO}/discussions/{GUESTBOOK}"


def splice(readme, marker, body):
    start, end = f"<!-- {marker}:START -->", f"<!-- {marker}:END -->"
    pattern = re.compile(
        re.escape(start) + r".*?" + re.escape(end), re.DOTALL
    )
    if not pattern.search(readme):
        sys.exit(f"Marker {marker} not found in README")
    return pattern.sub(f"{start}\n{body}\n{end}", readme)


def main():
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN is not set")

    repo = gql(token)
    readme = open("README.md").read()
    readme = splice(readme, "GUESTBOOK", render_notes(repo["discussion"]))
    readme = splice(readme, "THREADS", render_threads(repo["discussions"]))

    with open("README.md", "w") as fh:
        fh.write(readme)
    print("README updated")


if __name__ == "__main__":
    main()
