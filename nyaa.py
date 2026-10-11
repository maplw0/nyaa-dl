#!/usr/bin/env python3
"""Full-screen nyaa.si / sukebei.nyaa.si downloader that hands torrents to a qBittorrent Web UI (Windows).
Run: python nyaa.py [--qbit URL] [--user NAME] [--save PATH]   (see README.md)
Only torrents tagged 'nyaa-dl' are ever shown or touched."""
import argparse, getpass, json, msvcrt, os, re, shutil, time, unicodedata, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from types import SimpleNamespace as NS

QB = "http://localhost:8080"  # qBittorrent's default Web UI address; overridden by --qbit / QBIT_URL
TAG = "nyaa-dl"
SITES = ["nyaa.si", "sukebei.nyaa.si"]
UA = {"User-Agent": "Mozilla/5.0"}
HINTS = {
    "search": "Enter search / add pasted link   Left/Right site   Down results   Tab focus   Esc clear   Ctrl-C quit",
    "results": "Up/Down move   Space select   i info/files   a all   Enter download   / search   Tab downloads   q quit",
    "dl": "Up/Down move   i info/files   p pause/resume   x remove (keeps files)   c clear finished   Tab search   q quit",
    "view": "Up/Down/PgUp/PgDn/Home/End scroll   Esc or i close",
}
redraw = lambda: None  # set by main so slow actions can repaint first
stop_cmd, start_cmd = "stop", "start"  # qBittorrent v5 names; v4 uses pause/resume


def api_get(path, **params):
    url = f"{QB}/api/v2/{path}?{urllib.parse.urlencode(params)}"
    return urllib.request.urlopen(url, timeout=10).read().decode()


def api_post(path, fields, torrent=None):
    if torrent is None:
        req = urllib.request.Request(f"{QB}/api/v2/{path}", urllib.parse.urlencode(fields).encode())
    else:  # multipart upload of the .torrent we fetched locally
        b = "----nyaa" + os.urandom(8).hex()
        body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                        for k, v in fields.items())
        body += (f'--{b}\r\nContent-Disposition: form-data; name="torrents"; filename="x.torrent"\r\n'
                 f'Content-Type: application/x-bittorrent\r\n\r\n').encode() + torrent + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(f"{QB}/api/v2/{path}", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    return urllib.request.urlopen(req, timeout=20).read().decode()


def size(n):
    n = float(n)
    for u in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or u == "GiB":
            return f"{n:.1f} {u}"
        n /= 1024


def cw(c):  # terminal cells a character takes (Japanese is double-width)
    return 2 if unicodedata.east_asian_width(c) in "WF" else 1


def safe(c):  # untrusted text (titles, file names, descriptions) must never inject terminal escapes
    return "?" if unicodedata.category(c) in ("Cc", "Cf") else c  # control + invisible formatting (ESC, bidi overrides)


def fit(s, w):  # cut/pad to w terminal cells
    out, n = "", 0
    for c in map(safe, s):
        if n + cw(c) > w:
            break
        out, n = out + c, n + cw(c)
    return out + " " * (w - n)


def wrap(s, w):  # split into lines of at most w terminal cells
    out, cur, n = [], "", 0
    for c in map(safe, s):
        if n + cw(c) > w:
            out, cur, n = out + [cur], "", 0
        cur, n = cur + c, n + cw(c)
    return out + [cur]


def info_lines(f, page):
    """Text for the info screen of a search result: RSS fields + file tree and description from its nyaa page."""
    L = [f["title"], "",
         f"{f.get('category', '?')}  |  {f.get('size', '?')}  |  S:{f.get('seeders', '?')} L:{f.get('leechers', '?')}  |  "
         f"{f.get('downloads', '?')} downloads  |  {f.get('comments', '0')} comments",
         f"{f.get('pubDate', '')}  |  trusted: {f.get('trusted', '?')}  remake: {f.get('remake', '?')}",
         f"hash {f.get('infoHash', '')}", f.get("guid", ""), ""]
    block = re.search(r'torrent-file-list.*?</div>', page, re.S)
    tree, depth, nfiles = [], 0, 0
    for m in re.finditer(r'<ul[^>]*>|</ul>|class="folder"><i[^>]*></i>(.*?)</a>|'
                         r'<i class="fa fa-file"></i>(.*?)\s*<span class="file-size">\((.*?)\)</span>',
                         block[0] if block else "", re.S):
        if m[0].startswith("<ul"):
            depth += 1
        elif m[0] == "</ul>":
            depth -= 1
        elif m[1] is not None:
            tree.append("  " * (depth - 1) + unescape(m[1]) + "/")
        else:
            nfiles += 1
            tree.append("  " * (depth - 1) + f"{unescape(m[2])}  ({m[3]})")
    desc = re.search(r'id="torrent-description">(.*?)</div>', page, re.S)
    desc = unescape(desc[1]).replace("\r", "").replace("\t", "    ").strip() if desc else ""
    return L + [f"Files ({nfiles})"] + (tree or ["(couldn't read the file list)"]) + ["", "Description"] + \
           (desc.split("\n") if desc else ["(none)"])


def dl_info_lines(t, files):
    """Text for the info screen of a download: qBittorrent's own file list with per-file progress."""
    L = [t["name"], "", f"{t['state']}  |  {size(t['size'])}  |  {100 * t['progress']:.1f}%  |  saved in {t['save_path']}",
         f"hash {t['hash']}", "", f"Files ({len(files)})"]
    return L + [f"{fl['name']}  ({size(fl['size'])})  {100 * fl['progress']:.0f}%" for fl in files]


def search(host, q):
    url = f"https://{host}/?page=rss&q={urllib.parse.quote(q)}"
    feed = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read(5_000_000)
    rows = [{c.tag.split("}")[-1]: (c.text or "") for c in it} for it in ET.fromstring(feed).iter("item")]  # strip xml namespace
    rows.sort(key=lambda f: int(f.get("seeders") if str(f.get("seeders")).isdigit() else 0), reverse=True)  # RSS ignores sort params
    return rows


def check_url(u, strict):
    """Only http(s) is ever fetched. strict (links that came from a feed): https on the nyaa hosts only."""
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or (strict and not (p.scheme == "https" and p.hostname in SITES)):
        raise OSError(f"refusing to fetch {u[:60]!r}")


def to_torrent_url(u):
    m = re.match(r"(https?://(?:sukebei\.)?nyaa\.si)/view/(\d+)", u)
    return f"{m[1]}/download/{m[2]}.torrent" if m else u


def count(n):
    return n if n >= 0 else "?"  # qBittorrent reports -1 when the swarm size is unknown


def dl_row(t, w):
    done, total, speed = t["completed"], t["size"], t["dlspeed"]
    pct = 100 * t["progress"]
    eta = t["eta"] if 0 <= t["eta"] < 8640000 else 0  # 8640000 = qBittorrent's "infinity"
    stats = (f"{pct:5.1f}% [{'#' * int(pct // 10):<10}] {size(done):>9}/{size(total):<9} "
             f"{size(speed) + '/s':>11}  ETA {eta // 60}:{eta % 60:02d}  "
             f"S:{t['num_seeds']}/{count(t['num_complete'])} L:{t['num_leechs']}/{count(t['num_incomplete'])} {t['state']}")
    return fit(t["name"], max(10, w - len(stats) - 1)) + " " + stats


def refresh(st):
    try:
        data = json.loads(api_get("torrents/info", tag=TAG))
    except (OSError, ValueError):  # unreachable, or something other than qBittorrent answered
        st.msg = "qBittorrent not responding"
        return
    # belt and braces: never show or touch a torrent that isn't ours, even if the server ignored the tag filter
    st.dl = sorted((t for t in data if TAG in [x.strip() for x in t.get("tags", "").split(",")]), key=lambda t: t["added_on"])
    live = [t for t in st.dl if t["progress"] < 1 and not t["state"].startswith(("stopped", "paused", "error", "missing"))]
    st.g = {"numActive": sum(not t["state"].startswith("queued") for t in live),
            "numWaiting": sum(t["state"].startswith("queued") for t in live),
            "downloadSpeed": sum(t["dlspeed"] for t in st.dl)}


def draw(st, W, H):
    """Pure-ish: returns exactly H lines, each at most W-1 cells wide."""
    W -= 1
    R = max(4, H - 5)
    rh = max(2, R * 55 // 100)
    dh = R - rh
    st.cur = min(st.cur, max(0, len(st.results) - 1))
    st.dcur = min(st.dcur, max(0, len(st.dl) - 1))
    st.top = min(max(st.top, st.cur - rh + 1), st.cur)  # keep cursor in window
    st.dtop = min(max(st.dtop, st.dcur - dh + 1), st.dcur)

    def sep(t):
        return ("-- " + t + " " + "-" * W)[:W]

    def line(text, selected, focus):
        t = fit(text, W)
        return f"\x1b[7m{t}\x1b[0m" if selected and st.focus == focus else (f"\x1b[1m{t}\x1b[0m" if selected else t)

    if st.view:  # full-screen info page
        body = [r for l in st.view.lines for r in wrap(l, W)]
        bh = max(1, H - 3)
        st.view.top = max(0, min(st.view.top, len(body) - bh))
        shown = body[st.view.top: st.view.top + bh]
        L = [f"\x1b[1m{fit(st.view.lines[0], W)}\x1b[0m", sep(f"lines {st.view.top + 1}-{st.view.top + len(shown)} of {len(body)}")]
        L += [fit(l, W) for l in shown]
        return (L + [""] * H)[:H - 1] + [f"\x1b[2m{fit(HINTS['view'], W)}\x1b[0m"]

    tabs = " ".join(f"\x1b[7m {s} \x1b[0m" if i == st.site else f" {s} " for i, s in enumerate(SITES))
    g = st.g or {}
    L = [f" {tabs}   \x1b[33m{''.join(map(safe, st.msg))}\x1b[0m",
         fit(" Search: " + st.query + ("_" if st.focus == "search" else ""), W),
         sep(f"Results ({len(st.results)}), {len(st.sel)} selected")]
    for j in range(rh):
        i = st.top + j
        if i < len(st.results):
            f = st.results[i]
            L.append(line(f"[{'x' if i in st.sel else ' '}] S:{f.get('seeders', '?'):>4} L:{f.get('leechers', '?'):>4}"
                          f"  {f.get('size', '?'):>9}  {f['title']}", i == st.cur, "results"))
        else:
            L.append("")
    L.append(sep(f"qBittorrent {QB.split('//')[-1]}: {g.get('numActive', 0)} active, {g.get('numWaiting', 0)} queued, "
                 f"{size(g.get('downloadSpeed', 0))}/s"))
    body = [line(dl_row(st.dl[i], W), i == st.dcur, "dl") for i in range(st.dtop, min(len(st.dl), st.dtop + dh))]
    L += (body + [""] * dh)[:dh]
    L.append(f"\x1b[2m{fit(HINTS[st.focus], W)}\x1b[0m")
    return (L + [""] * H)[:H]


def paint(st):
    W, H = shutil.get_terminal_size()
    print("\x1b[H" + "\n".join(l + "\x1b[K" for l in draw(st, W, H)), end="", flush=True)


def add(st, urls, strict=False):
    for u in urls:
        fields = {"tags": TAG, **({"savepath": st.save} if st.save else {})}
        if u.startswith("magnet:"):
            r = api_post("torrents/add", {**fields, "urls": u})
        else:  # fetch the .torrent here so the server doesn't need to reach nyaa itself
            u = to_torrent_url(u)
            check_url(u, strict)
            blob = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read(10_000_000)
            r = api_post("torrents/add", fields, torrent=blob)
        if "Ok" not in r:
            raise OSError(f"qBittorrent said {r.strip()!r}")
    st.msg = f"added {len(urls)} download(s)"


def act(path, hashes, **extra):
    api_post(f"torrents/{path}", {"hashes": "|".join(hashes), **extra})


def handle(st, k):
    """Apply one key to the state; returns False when the app should exit (downloads keep running on the server)."""
    st.msg = ""
    if k == "\x03":
        return False
    if st.view:
        step = {"up": -1, "down": 1, "pgup": -10, "pgdn": 10}
        if k in step:
            st.view.top = max(0, st.view.top + step[k])
        elif k == "home":
            st.view.top = 0
        elif k == "end":
            st.view.top = 10 ** 9  # draw() clamps it
        elif k in ("\x1b", "q", "i", "\r"):
            st.view = None
        return True
    if k in ("left", "right"):
        st.site = 0 if k == "left" else 1
    elif k == "\t":
        st.focus = {"search": "results", "results": "dl", "dl": "search"}[st.focus]
    elif st.focus == "search":
        if k == "\r":
            q = st.query.strip()
            try:
                if q.startswith(("http", "magnet:")):
                    add(st, [q])
                    st.query = ""
                elif q:
                    st.msg = "searching..."
                    redraw()
                    st.results, st.sel, st.cur, st.top = search(SITES[st.site], q), set(), 0, 0
                    st.msg = "" if st.results else "no results"
                    st.focus = "results" if st.results else "search"
            except (OSError, ValueError) as e:
                st.msg = f"error: {e}"
            except ET.ParseError:
                st.msg = "bad response from site"
        elif k == "\b":
            st.query = st.query[:-1]
        elif k == "\x1b":
            st.query = ""
        elif k == "down" and st.results:
            st.focus = "results"
        elif len(k) == 1 and k.isprintable():
            st.query += k
    elif k == "q":
        return False
    elif st.focus == "results":
        n = len(st.results)
        if k == "up" and st.cur == 0:
            st.focus = "search"
        elif k in ("up", "down", "pgup", "pgdn", "home", "end") and n:
            st.cur = {"up": st.cur - 1, "down": st.cur + 1, "pgup": st.cur - 10, "pgdn": st.cur + 10,
                      "home": 0, "end": n - 1}[k]
            st.cur = max(0, min(n - 1, st.cur))
        elif k == " " and n:
            st.sel ^= {st.cur}
            st.cur = min(n - 1, st.cur + 1)
        elif k == "a" and n:
            st.sel = set() if len(st.sel) == n else set(range(n))
        elif k == "i" and n:
            try:
                st.msg = "loading..."
                redraw()
                check_url(st.results[st.cur].get("guid", ""), True)
                page = urllib.request.urlopen(urllib.request.Request(st.results[st.cur]["guid"], headers=UA), timeout=20)
                st.view = NS(lines=info_lines(st.results[st.cur], page.read(3_000_000).decode("utf-8", "replace")), top=0)
                st.msg = ""
            except (OSError, ValueError) as e:
                st.msg = f"error: {e}"
        elif k == "\r" and n:
            try:
                add(st, [st.results[i].get("link", "") for i in sorted(st.sel or {st.cur})], strict=True)
                st.sel = set()
            except (OSError, ValueError) as e:
                st.msg = f"error: {e}"
        elif k in ("/", "\x1b"):
            st.focus = "search"
    elif st.focus == "dl":
        if k in ("up", "down") and st.dl:
            st.dcur = max(0, min(len(st.dl) - 1, st.dcur + (1 if k == "down" else -1)))
        elif k == "\x1b":
            st.focus = "search"
        try:
            if k == "c":  # only finished torrents we added; files stay on disk
                done = [t["hash"] for t in st.dl if t["progress"] >= 1]
                if done:
                    act("delete", done, deleteFiles="false")
            elif k == "i" and st.dl:
                t = st.dl[st.dcur]
                st.view = NS(lines=dl_info_lines(t, json.loads(api_get("torrents/files", hash=t["hash"]))), top=0)
            elif k in ("p", "x") and st.dl:
                t = st.dl[st.dcur]
                if k == "p":
                    act(start_cmd if t["state"].startswith(("stopped", "paused")) else stop_cmd, [t["hash"]])
                else:
                    act("delete", [t["hash"]], deleteFiles="false")
        except (OSError, ValueError) as e:
            st.msg = f"error: {e}"
    return True


def getkey(timeout=0.5):
    end = time.time() + timeout
    while time.time() < end:
        if msvcrt.kbhit():
            c = msvcrt.getwch()
            if c in "\x00\xe0":
                return {"H": "up", "P": "down", "K": "left", "M": "right", "I": "pgup", "Q": "pgdn",
                        "G": "home", "O": "end"}.get(msvcrt.getwch(), "?")
            return c
        time.sleep(0.03)
    return None  # timeout: caller just repaints (live download stats)


def connect(url, user="", password=""):
    """Log in (if a user is given), pick the v4/v5 endpoint names; exits with a clear message if unreachable."""
    global QB, stop_cmd, start_cmd
    QB = url.rstrip("/")
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPCookieProcessor()))  # keeps the login session
    try:
        if user and "Ok" not in api_post("auth/login", {"username": user, "password": password}):
            raise SystemExit("qBittorrent rejected that username/password")
        ver = api_get("app/version").strip()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"qBittorrent at {QB} answered HTTP {e.code}: it needs a login. Pass --user (see README)")
    except (OSError, ValueError) as e:
        raise SystemExit(f"can't reach qBittorrent at {QB}: {e}")
    if not ver.lstrip("v").startswith(("5", "6", "7")):
        stop_cmd, start_cmd = "pause", "resume"
    return ver


def main():
    global redraw
    ap = argparse.ArgumentParser(description="Search nyaa.si / sukebei.nyaa.si and send torrents to qBittorrent.")
    ap.add_argument("--qbit", default=os.environ.get("QBIT_URL", QB), help="qBittorrent Web UI url (env QBIT_URL)")
    ap.add_argument("--user", default=os.environ.get("QBIT_USER", ""), help="Web UI username, if it needs a login (env QBIT_USER)")
    ap.add_argument("--save", default="", help="save path as the *server* sees it, e.g. /data/torrents/nyaa (default: qBittorrent's)")
    a = ap.parse_args()
    # no --password flag on purpose: command lines show up in process lists and shell history
    password = os.environ.get("QBIT_PASS", "") or (getpass.getpass(f"qBittorrent password for {a.user}: ") if a.user else "")
    connect(a.qbit, a.user, password)
    os.system("")  # enables ANSI escapes on Windows consoles
    st = NS(save=a.save, site=0, query="", results=[], sel=set(), cur=0, top=0, dl=[], dcur=0, dtop=0,
            focus="search", msg="", g={}, view=None)
    redraw = lambda: paint(st)
    print("\x1b[?1049h\x1b[?25l\x1b[2J", end="")  # alt screen, hide cursor
    try:
        while True:
            refresh(st)
            paint(st)
            try:
                k = getkey()
            except KeyboardInterrupt:
                k = "\x03"
            if k is not None and not handle(st, k):
                break
    finally:
        print("\x1b[?25h\x1b[?1049l", end="")


if __name__ == "__main__":
    main()
