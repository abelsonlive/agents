#!/usr/bin/env python3
"""Keyless Reddit search. No API key, no registration, stdlib only.

Two sources:
  live    — reddit.com .rss endpoints. Current data. No scores. Rate-limited.
  archive — api.pullpush.io. Has scores + comment full-text search.
            Frozen: contains nothing after 2025-05-19.

Output is compact by default (one line per hit) to stay cheap in an agent's
context. Use --full for bodies, --json for machine parsing.
"""
import argparse, collections, html, json, re, sys, time
import urllib.parse, urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
PULLPUSH = "https://api.pullpush.io/reddit/search"
ARCHIVE_END = "2025-05-19"  # last day pullpush ingested
ATOM = {"a": "http://www.w3.org/2005/Atom"}


# ---------------------------------------------------------------- fetching

def _fetch(url, tries=6):
    """GET with backoff. Reddit's RSS 429s aggressively; waiting clears it."""
    delay, last = 5, None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            code = getattr(e, "code", None)
            if code == 404:
                raise SystemExit("reddit_search: 404 — no such subreddit or thread id")
            if code and code not in (429, 500, 502, 503, 504):
                raise SystemExit(f"reddit_search: HTTP {code} for {url}")
            if i < tries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
    raise SystemExit(f"reddit_search: request failed after {tries} tries: {last}")


def _json(url):
    return json.loads(_fetch(url)).get("data", [])


# ---------------------------------------------------------------- cleaning

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# RSS wraps every body in this footer; it is pure noise in an agent's context.
_RSS_FOOTER = re.compile(r"\s*submitted by\s*/u/\S+\s*to\s*r/\S+\s*(\[link\])?\s*(\[comments\])?\s*$")


def clean(text, limit):
    """HTML -> flat text, whitespace collapsed, truncated to a token budget."""
    if not text:
        return ""
    t = html.unescape(_TAG.sub(" ", html.unescape(text)))
    t = _WS.sub(" ", t).strip()
    t = _RSS_FOOTER.sub("", t)
    if limit and len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "…"
    return t


def _epoch(d):
    return int(time.mktime(time.strptime(d, "%Y-%m-%d")))


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts or 0))


# ---------------------------------------------------------------- live (rss)

def rss_entries(path, params):
    url = f"https://www.reddit.com/{path}?" + urllib.parse.urlencode(params)
    try:
        root = ET.fromstring(_fetch(url))
    except ET.ParseError:
        return []
    out = []
    for e in root.findall("a:entry", ATOM):
        cat = e.find("a:category", ATOM)
        author = e.find("a:author/a:name", ATOM)
        link = e.find("a:link", ATOM)
        pub = e.findtext("a:published", "", ATOM)
        raw_id = e.findtext("a:id", "", ATOM) or ""
        # Sitewide search mixes in subreddit entities (t5_); posts are t3_,
        # comments t1_. Callers filter on this.
        kind, _, ident = raw_id.partition("_")
        out.append({
            "kind": kind,
            "id": ident or raw_id,
            "date": pub[:10],
            "subreddit": ((cat.get("label") or cat.get("term")) if cat is not None else "").removeprefix("r/"),
            "author": (author.text if author is not None else "").removeprefix("/u/"),
            "title": e.findtext("a:title", "", ATOM),
            "url": link.get("href") if link is not None else "",
            "body": e.findtext("a:content", "", ATOM),
        })
    return out


def live_search(query, sub, sort, window, limit):
    params = {"q": query, "sort": sort, "t": window, "limit": min(limit, 100)}
    path = f"r/{sub}/search.rss" if sub else "search.rss"
    if sub:
        params["restrict_sr"] = 1
    rows = [r for r in rss_entries(path, params) if r["kind"] == "t3"]
    return rows[:limit]


# ------------------------------------------------------------- archive (pp)

def archive_search(query, sub, limit, since, until, kind="submission"):
    p = {"size": str(min(limit, 100)), "sort": "desc",
         "sort_type": "score" if kind == "submission" else "created_utc"}
    if query:
        p["q"] = query
    if sub:
        p["subreddit"] = sub
    if since:
        p["after"] = str(_epoch(since))
    if until:
        p["before"] = str(_epoch(until))
    rows = _json(f"{PULLPUSH}/{kind}/?" + urllib.parse.urlencode(p))
    out = []
    for d in rows:
        out.append({
            "id": d.get("id", ""),
            "date": _day(d.get("created_utc")),
            "subreddit": d.get("subreddit", ""),
            "author": d.get("author", ""),
            "score": d.get("score"),
            "comments": d.get("num_comments"),
            "title": d.get("title") or "",
            "url": "https://www.reddit.com" + (d.get("permalink") or ""),
            "body": d.get("selftext") or d.get("body") or "",
        })
    return out


# ---------------------------------------------------------------- rendering

def emit(rows, args, note=""):
    if args.json:
        for r in rows:
            r["body"] = clean(r.get("body"), args.chars if args.full else 0)
        print(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
        return
    if not rows:
        print(f"no results{(' — ' + note) if note else ''}")
        return
    for r in rows:
        stat = ""
        if r.get("score") is not None:
            stat = f"  ^{r['score']}"
            if r.get("comments") is not None:
                stat += f" c{r['comments']}"
        # Comment hits carry no title; identify them by author instead.
        label = r["title"] or f"u/{r.get('author', '?')}"
        print(f"{r['id']}  {r['date']}  r/{r['subreddit']}{stat}  {label}")
        if args.full:
            b = clean(r.get("body"), args.chars)
            if b:
                print(f"    {b}")
    if note:
        print(f"\n[{note}]")


# ---------------------------------------------------------------- commands

def cmd_search(a):
    if a.archive:
        rows = archive_search(a.query, a.subreddit, a.limit, a.since, a.until)
        note = f"archive (pullpush); no data after {ARCHIVE_END}"
    else:
        rows = live_search(a.query, a.subreddit, a.sort, a.window, a.limit)
        note = ("live (reddit rss); --sort top ranks by true score, "
                "the numbers just aren't exposed — use --archive to see them")
    emit(rows, a, note)


def cmd_subs(a):
    """Which subreddits actually discuss this topic?

    Sitewide sort=top surfaces all-time viral posts regardless of topic
    (r/television for "cast iron seasoning"); relevance over a quoted phrase
    lands the real home sub. Both are hardcoded — they are the whole method.
    """
    q = a.query if '"' in a.query or " " not in a.query else f'"{a.query}"'
    rows = live_search(q, None, "relevance", a.window, 100)
    src = "live"
    if not rows:
        rows = archive_search(a.query, None, 100, None, None)
        src = "archive"
    tally = collections.Counter(r["subreddit"] for r in rows if r["subreddit"])
    if a.json:
        print(json.dumps(tally.most_common(a.limit), ensure_ascii=False))
        return
    if not tally:
        print("no results")
        return
    for sub, n in tally.most_common(a.limit):
        print(f"{n:4}  r/{sub}")
    print(f"\n[{src}: {len(rows)} posts matching {a.query!r}, by subreddit]")


def cmd_thread(a):
    sid = a.url
    m = re.search(r"/comments/([a-z0-9]+)", a.url)
    if m:
        sid = m.group(1)
    sid = sid.replace("t3_", "").strip()

    if a.archive:
        post = _json(f"{PULLPUSH}/submission/?ids={sid}")
        p = post[0] if post else {}
        head = {"title": p.get("title", ""), "url": "https://www.reddit.com" + (p.get("permalink") or ""),
                "subreddit": p.get("subreddit", ""), "score": p.get("score"),
                "body": p.get("selftext", "")}
        cm = _json(f"{PULLPUSH}/comment/?link_id={sid}&size={a.limit}&sort=desc&sort_type=score")
        comments = [{"author": c.get("author"), "score": c.get("score"),
                     "body": c.get("body", "")} for c in cm]
    else:
        rows = rss_entries(f"comments/{sid}.rss", {"sort": "top", "limit": a.limit})
        if not rows:
            print(f"no thread {sid} (try --archive)")
            return
        head = {"title": rows[0]["title"], "url": rows[0]["url"],
                "subreddit": rows[0]["subreddit"], "score": None,
                "body": rows[0]["body"]}
        comments = [{"author": r["author"], "score": None, "body": r["body"]}
                    for r in rows[1:a.limit + 1]]

    if a.json:
        head["body"] = clean(head["body"], a.chars * 3)
        for c in comments:
            c["body"] = clean(c["body"], a.chars)
        print(json.dumps({**head, "comments": comments}, ensure_ascii=False, separators=(",", ":")))
        return
    print(f"{head['title']}  [r/{head['subreddit']}]")
    print(head["url"])
    body = clean(head["body"], a.chars * 3)
    if body:
        print(f"\n{body}")
    print(f"\n-- {len(comments)} comments --")
    for c in comments:
        s = f" ^{c['score']}" if c.get("score") is not None else ""
        b = clean(c["body"], a.chars)
        if b:
            print(f"\n[{c['author']}{s}] {b}")


def cmd_comments(a):
    rows = archive_search(a.query, a.subreddit, a.limit, a.since, a.until, kind="comment")
    a.full = True
    emit(rows, a, f"archive-only (live reddit has no comment search); nothing after {ARCHIVE_END}")


# ---------------------------------------------------------------- cli

def main():
    # Output flags live on a shared parent so they work either before or after
    # the subcommand — argparse otherwise rejects `search foo --full`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--full", action="store_true", help="include post/comment bodies")
    common.add_argument("--chars", type=int, default=500,
                        help="body truncation (default 500)")

    p = argparse.ArgumentParser(
        parents=[common],
        description="Keyless Reddit search (live rss + pullpush archive)")
    sp = p.add_subparsers(dest="cmd")

    s = sp.add_parser("search", parents=[common], help="search posts")
    s.add_argument("query")
    s.add_argument("-r", "--subreddit")
    s.add_argument("-n", "--limit", type=int, default=25)
    s.add_argument("--sort", default="relevance",
                   choices=["relevance", "top", "new", "comments"])
    s.add_argument("-t", "--window", default="all",
                   choices=["hour", "day", "week", "month", "year", "all"])
    s.add_argument("--archive", action="store_true", help="use pullpush (adds scores)")
    s.add_argument("--since"), s.add_argument("--until")
    s.set_defaults(func=cmd_search)

    s = sp.add_parser("subs", parents=[common], help="discover which subreddits discuss a topic")
    s.add_argument("query")
    s.add_argument("-n", "--limit", type=int, default=15)
    s.add_argument("-t", "--window", default="all",
                   choices=["hour", "day", "week", "month", "year", "all"])
    s.set_defaults(func=cmd_subs)

    s = sp.add_parser("thread", parents=[common], help="one thread: post + top comments")
    s.add_argument("url", help="permalink or post id")
    s.add_argument("-n", "--limit", type=int, default=25)
    s.add_argument("--archive", action="store_true", help="use pullpush (adds scores)")
    s.set_defaults(func=cmd_thread)

    s = sp.add_parser("comments", parents=[common], help="full-text comment search (archive only)")
    s.add_argument("query")
    s.add_argument("-r", "--subreddit")
    s.add_argument("-n", "--limit", type=int, default=25)
    s.add_argument("--since"), s.add_argument("--until")
    s.set_defaults(func=cmd_comments)

    a = p.parse_args()
    if not a.cmd:
        p.print_help()
        sys.exit(1)
    a.func(a)


if __name__ == "__main__":
    main()
