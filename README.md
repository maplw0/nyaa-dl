# nyaa-dl

A full-screen terminal app for searching [nyaa.si](https://nyaa.si) and [sukebei.nyaa.si](https://sukebei.nyaa.si)
and sending the torrents you pick to your own **qBittorrent**. Search, tick a few results, press Enter, and watch
them download, all from one screen.

```
 nyaa.si  [sukebei.nyaa.si]
 Search: some show_
-- Results (53), 2 selected ----------------------------------------------------------
[x] S:  47 L:   3   659.7 MiB  [Group] Some Show - 03-04
[x] S:  45 L:   1   575.6 MiB  [Group] Some Show - 01-02
[ ] S:  13 L:   0    10.6 GiB  [Group] Some Show (Batch)
-- qBittorrent localhost:8080: 2 active, 0 queued, 3.1 MiB/s -------------------------
[Group] Some Show - 01-02   45.2% [####      ]  258.4 MiB/571.0 MiB  1.2 MiB/s  ETA 4:12  S:5/45 L:2/3 downloading
 Up/Down move   Space select   i info/files   a all   Enter download   / search   Tab downloads   q quit
```

- Search both sites and switch between them with one key.
- Multi-select results and download them all at once.
- Press `i` to see a torrent's **file list** and **description** before downloading.
- Live downloads panel: progress, speed, ETA, seeders/leechers, pause / resume / remove.
- Downloads run inside qBittorrent, so **closing the app does not stop them**.
- It only ever shows or touches torrents it added itself (tagged `nyaa-dl`). Your other torrents, such as
  Sonarr or Radarr ones, are never listed, paused or removed. Removing a torrent here never deletes files.
- No dependencies: Python standard library only.

## Requirements

- **Windows** (the keyboard handling uses `msvcrt`). [Windows Terminal](https://aka.ms/terminal) is recommended.
- **Python 3.8 or newer**: <https://www.python.org/downloads/>
- **qBittorrent** (v4.3.2 or newer; v5 works) with its **Web UI** turned on. It can run on this PC or on another
  machine such as a home server or a NAS.

## Setup

### 1. Turn on qBittorrent's Web UI

In qBittorrent: **Tools -> Options -> Web UI**

1. Tick **Web User Interface (Remote control)**. The default port is `8080`.
2. Choose how this app gets in. Pick one:
   - **Username and password** (works everywhere): set them under *Authentication*. Fresh installs of recent
     versions print a temporary random password to qBittorrent's log the first time it starts; change it here.
   - **No login for trusted machines**: tick *Bypass authentication for clients on localhost* (app and qBittorrent
     on the same PC) or *Bypass authentication for clients in whitelisted IP subnets* (for example your home network
     `192.168.1.0/24`). Only do this on a network you trust.
3. Click **Apply**.

Running qBittorrent in Docker? The `linuxserver/qbittorrent` image enables the Web UI on `WEBUI_PORT` (default
`8080`); set its username and password the same way from the Web UI settings.

Check it works by opening `http://localhost:8080` (or `http://<server-ip>:8080`) in your browser.

### 2. Get the app

```bash
git clone https://github.com/maplw0/nyaa-dl.git
cd nyaa-dl
```

(Or download `nyaa.py` on its own. It is the whole app.)

### 3. Run it

qBittorrent on the same PC, no login needed:

```bash
python nyaa.py
```

qBittorrent on another machine, with a login:

```bash
python nyaa.py --qbit http://192.168.1.50:8080 --user admin
```

It asks for the password (typing is hidden). To skip the prompt, set environment variables instead (nothing ends
up in your shell history or in the repo):

```powershell
$env:QBIT_URL  = "http://192.168.1.50:8080"
$env:QBIT_USER = "admin"
$env:QBIT_PASS = "your-password"
python nyaa.py
```

## Using it

| Where | Key | Does |
|---|---|---|
| Anywhere | `Tab` | cycle focus: search box -> results -> downloads |
| Anywhere | `Left` / `Right` | switch between nyaa.si and sukebei.nyaa.si |
| Anywhere | `Ctrl-C` | quit (downloads keep running in qBittorrent) |
| Search box | type + `Enter` | search |
| Search box | paste a **magnet link**, `.torrent` URL or nyaa `/view/...` link + `Enter` | download it directly |
| Search box | `Esc` | clear the box |
| Search box | `Down` | jump to the results |
| Results | `Up` / `Down` / `PgUp` / `PgDn` / `Home` / `End` | move |
| Results | `Space` | tick / untick, then move down |
| Results | `a` | select all / none |
| Results | `Enter` | download the ticked results (or the highlighted one if none ticked) |
| Results | `i` | info page: file list and the uploader's description |
| Results | `/` or `Esc` | back to the search box |
| Downloads | `Up` / `Down` | move |
| Downloads | `p` | pause / resume |
| Downloads | `x` | remove from qBittorrent (**keeps the downloaded files**) |
| Downloads | `c` | clear finished downloads from the list (keeps files) |
| Downloads | `i` | file list with per-file progress |
| Results / Downloads | `q` | quit |
| Info page | arrows, `PgUp`, `PgDn`, `Home`, `End` | scroll |
| Info page | `Esc` or `i` | close |

In the results, `S:` is seeders and `L:` is leechers as reported by the site. In the downloads panel, `S:a/b`
means connected seeders / total seeders in the swarm (same for `L:`); `?` means qBittorrent doesn't know yet.

### Options

| Option | Env var | Meaning |
|---|---|---|
| `--qbit URL` | `QBIT_URL` | qBittorrent Web UI address (default `http://localhost:8080`) |
| `--user NAME` | `QBIT_USER` | Web UI username, if it needs a login |
| `--password PW` | `QBIT_PASS` | Web UI password (prompted for if you pass `--user` without it; prefer the env var or the prompt over this flag) |
| `--save PATH` | | where qBittorrent should save new downloads (default: qBittorrent's own default) |

`--save` is a path **as qBittorrent sees it**. If qBittorrent runs in Docker or on another machine, that is the
path inside the container or on that machine, for example `/data/torrents/nyaa`, not a Windows path.

## Troubleshooting

- **"can't reach qBittorrent"**: wrong address or port, the Web UI isn't enabled, or a firewall is in the way.
  Open the same address in a browser to check.
- **"HTTP 403 ... needs a login"**: add `--user`, or allow your machine to skip authentication (step 1). If you
  just entered a login and it keeps failing, qBittorrent may have temporarily banned your IP after repeated
  wrong passwords; wait a while or restart qBittorrent.
- **"qBittorrent rejected that username/password"**: check them in qBittorrent's Web UI settings.
- **Through a reverse proxy or hostname, requests are refused**: add the hostname to *Web UI -> Server domains*
  or relax *Host header validation* / *CSRF protection*.
- **Garbled lines or stray characters**: use Windows Terminal and make the window a bit wider.
- **Info page shows "(couldn't read the file list)"**: nyaa changed its page layout; the file list is read from
  the site's HTML, so it may need a small update.

## Notes

- Search uses the sites' public RSS feeds; the info page reads the torrent's public web page. The `.torrent`
  file is fetched on your PC and uploaded to qBittorrent, so the qBittorrent machine never needs to reach nyaa.
- sukebei.nyaa.si is the adult section of nyaa. Only use it if you are of legal age where you live.
- You are responsible for what you download. Only download content you have the right to.
