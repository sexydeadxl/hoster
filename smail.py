#!/usr/bin/env python3
"""
smail.py - single-file smailpro temporary-mail client. arrow-key TUI, no server.

    python smail.py            interactive menu (arrows / enter)
    python smail.py new [dom]  one-shot create
    python smail.py list       one-shot list

Deps:  pip install curl_cffi
"""

from __future__ import annotations

import html as htmllib
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

try:
    from curl_cffi import requests as cr
except ImportError:
    print("missing dependency ->  pip install curl_cffi")
    sys.exit(1)

if os.name == "nt":
    import msvcrt

    import ctypes
    _k32 = ctypes.windll.kernel32
    _hout = _k32.GetStdHandle(-11)
    _mode = ctypes.c_uint32()
    if _k32.GetConsoleMode(_hout, ctypes.byref(_mode)):
        _k32.SetConsoleMode(_hout, _mode.value | 0x0004)  # ANSI escapes on
else:
    import termios
    import tty

# --------------------------------------------------------------------- config
BASE = "https://smailpro.com"
PAGE = f"{BASE}/temporary-email"
SITEKEY = "0x4AAAAAAABIS_gEec2IwOhI"
SONJJ = "https://api.sonjj.com/v1"

XSOLVE_URL = os.getenv("XSOLVE_URL", "https://api.xsolve.me/task")
XSOLVE_KEY = os.getenv("XSOLVE_KEY", "4cdb9033c22b9b7913c2bc6fc299e32d")
FALLBACK_SOLVER = os.getenv("SMAIL_SOLVER_URL", "http://82.38.134.61:9876/turnstile")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")

STORE = Path(os.getenv("SMAIL_STORE", Path(__file__).with_name("mailboxes.json")))

PROVIDER_PATHS = {"google": "temp_gmail", "microsoft": "temp_outlook", "other": "temp_email"}
GOOGLE_DOMAINS = {"gmail.com", "googlemail.com"}
MS_DOMAINS = {"outlook.com", "hotmail.com", "outlook.kr", "outlook.fr", "outlook.com.vn",
              "outlook.co.id", "outlook.co.th", "outlook.com.ar", "outlook.co.il"}

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.8",
    "content-type": "application/json",
    "dnt": "1",
    "origin": BASE,
    "referer": PAGE,
    "sec-ch-ua": '"Brave";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "sec-gpc": "1",
    "user-agent": UA,
}


class SmailError(RuntimeError):
    pass


def provider_for(address: str) -> str:
    d = address.rsplit("@", 1)[-1].lower()
    if d in GOOGLE_DOMAINS:
        return "google"
    if d in MS_DOMAINS:
        return "microsoft"
    return "other"


# --------------------------------------------------------------------- solver
def solve_turnstile(url: str = PAGE, sitekey: str = SITEKEY, attempts: int = 3) -> str:
    errs = []
    for i in range(attempts):
        try:
            r = cr.post(XSOLVE_URL,
                        headers={"x-api-key": XSOLVE_KEY, "content-type": "application/json"},
                        json={"mode": "turnstile", "url": url, "sitekey": sitekey},
                        timeout=90, impersonate="chrome")
            d = r.json()
            if d.get("token"):
                return d["token"]
            errs.append(f"xsolve {r.status_code} {r.text[:120]}")
        except Exception as exc:  # noqa: BLE001
            errs.append(f"xsolve {exc!r}")

        if FALLBACK_SOLVER:
            try:
                r = cr.post(FALLBACK_SOLVER, headers={"content-type": "application/json"},
                            json={"url": url, "sitekey": sitekey}, timeout=120,
                            impersonate="chrome")
                d = r.json()
                if d.get("token"):
                    return d["token"]
                errs.append(f"fallback {r.status_code}")
            except Exception as exc:  # noqa: BLE001
                errs.append(f"fallback {exc!r}")

        if i < attempts - 1:
            time.sleep(1.5 * (i + 1))
    raise SmailError("solver failed: " + " | ".join(errs[-3:]))


# --------------------------------------------------------------------- client
class Smail:
    def __init__(self, timeout: int = 45):
        self.s = cr.Session(impersonate="chrome")
        self.timeout = timeout
        self._warm = False

    def warm(self):
        if not self._warm:
            try:
                self.s.get(PAGE, headers={"user-agent": UA}, timeout=self.timeout)
            finally:
                self._warm = True

    def _h(self, captcha=None):
        h = dict(HEADERS)
        if captcha:
            h["x-captcha"] = captcha
        return h

    def create(self, domain="outlook.com", username="random", type_="alias", server=1):
        self.warm()
        r = self.s.get(f"{BASE}/app/create",
                       params={"username": username, "type": type_,
                               "domain": domain, "server": server},
                       headers=self._h(solve_turnstile()), timeout=self.timeout)
        if r.status_code == 403:
            raise SmailError("turnstile rejected (403)")
        if r.status_code != 200:
            detail = r.text[:200]
            if "premium" in detail.lower():
                raise SmailError("custom usernames are premium-only on smailpro - "
                                 "use a random address (username='random')")
            raise SmailError(f"create {r.status_code}: {detail}")
        d = r.json()
        if not d.get("address"):
            raise SmailError(f"create: {str(d)[:200]}")
        return d

    def recover(self, address):
        user, _, domain = address.partition("@")
        return self.create(domain=domain, username=user)

    def inbox(self, box):
        r = self.s.post(f"{BASE}/app/inbox", headers=self._h(),
                        data=json.dumps([{"address": box["address"],
                                          "timestamp": box["timestamp"],
                                          "key": box["key"]}]),
                        timeout=self.timeout)
        if r.status_code != 200:
            raise SmailError(f"app/inbox {r.status_code}: {r.text[:200]}")
        rows = r.json()
        if not rows:
            raise SmailError("empty response - key expired?")
        row = rows[0]
        box = {"address": row["address"],
               "timestamp": row.get("timestamp", box["timestamp"]),
               "key": row.get("key", box["key"])}
        st = self.s.get(f"{SONJJ}/{PROVIDER_PATHS[provider_for(box['address'])]}/inbox",
                        params={"payload": row["payload"]},
                        headers={"accept": "*/*", "origin": BASE, "referer": f"{BASE}/",
                                 "user-agent": UA}, timeout=self.timeout)
        if st.status_code != 200:
            raise SmailError(f"sonjj inbox {st.status_code}: {st.text[:200]}")
        return st.json().get("messages", []), box

    def _msg_payload(self, address, mid, file_id=None):
        params = {"email": address, "mid": mid}
        if file_id:
            params["file_id"] = file_id
        r = self.s.get(f"{BASE}/app/message", params=params,
                       headers=self._h(solve_turnstile()), timeout=self.timeout)
        if r.status_code == 403:
            raise SmailError("message 403 - mailbox key expired, recover it")
        if r.status_code != 200:
            raise SmailError(f"app/message {r.status_code}: {r.text[:200]}")
        p = r.text.strip()
        if not p or p.startswith("{"):
            raise SmailError(f"no payload: {p[:150]}")
        return p

    def message(self, address, mid):
        p = self._msg_payload(address, mid)
        r = self.s.get(f"{SONJJ}/{PROVIDER_PATHS[provider_for(address)]}/message",
                       params={"payload": p},
                       headers={"accept": "*/*", "origin": BASE, "referer": f"{BASE}/",
                                "user-agent": UA}, timeout=self.timeout)
        if r.status_code != 200:
            raise SmailError(f"sonjj message {r.status_code}: {r.text[:200]}")
        return r.json()

    def attachment(self, address, mid, file_id):
        p = self._msg_payload(address, mid, file_id)
        r = self.s.get(f"{SONJJ}/temp_email/attachments", params={"payload": p}, timeout=90)
        if r.status_code != 200:
            raise SmailError(f"attachment {r.status_code}")
        return r.content

    def wait_for_mail(self, box, seconds=60, interval=2):
        """Fixed-rate polling: one inbox fetch every `interval` seconds wall-clock."""
        start = time.time()
        while True:
            t0 = time.time()
            msgs, box = self.inbox(box)
            if msgs or time.time() - start >= seconds:
                return msgs, box
            time.sleep(max(0.0, interval - (time.time() - t0)))


# ---------------------------------------------------------------------- store
def load_boxes() -> dict:
    if not STORE.exists():
        return {}
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_boxes(data: dict):
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def remember(box: dict):
    data = load_boxes()
    data[box["address"].lower()] = {
        "address": box["address"],
        "timestamp": box["timestamp"],
        "key": box["key"],
        "provider": provider_for(box["address"]),
        "created_at": int(time.time()),
    }
    save_boxes(data)


def forget(address: str) -> bool:
    data = load_boxes()
    gone = data.pop(address.lower(), None) is not None
    save_boxes(data)
    return gone


# ---------------------------------------------------------------- text helpers
def strip_html(raw: str, limit: int = 6000) -> str:
    if not raw:
        return ""
    txt = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    txt = re.sub(r"(?i)<br\s*/?>", "\n", txt)
    txt = re.sub(r"(?i)</p>", "\n\n", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = htmllib.unescape(txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt[:limit]


# ------------------------------------------------------------------------ tui
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
INV = "\x1b[7m"

W = 62


def clear():
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def hide_cursor():
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()


def show_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


def getkey() -> str:
    """up / down / enter / esc / char"""
    if os.name == "nt":
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            nxt = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(nxt, "")
        if ch == "\r":
            return "enter"
        if ch == "\x1b":
            return "esc"
        if ch == "\x03":
            return "quit"
        return ch

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            nxt = sys.stdin.read(2)
            return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(nxt, "esc")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            return "quit"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def banner(title: str, sub: str = ""):
    print(f"  {BOLD}{CYAN}{title}{RESET}")
    print(f"  {DIM}{'-' * W}{RESET}")
    if sub:
        print(f"  {DIM}{sub}{RESET}")
        print()


def select(title: str, items: list[str], sub: str = "", allow_back: bool = True) -> int | None:
    """Arrow-key menu. Returns index or None on esc/back."""
    if not items:
        return None
    idx = 0
    hide_cursor()
    try:
        while True:
            clear()
            banner(title, sub)
            for i, item in enumerate(items):
                if i == idx:
                    print(f"  {INV}{GREEN} > {i + 1:>2}. {item}{RESET}")
                else:
                    print(f"    {DIM}{i + 1:>2}.{RESET} {item}")
            print()
            hint = "up/down + enter" + ("  -  esc = back" if allow_back else "")
            print(f"  {DIM}{hint}{RESET}")
            k = getkey()
            if k == "up":
                idx = (idx - 1) % len(items)
            elif k == "down":
                idx = (idx + 1) % len(items)
            elif k == "enter":
                return idx
            elif k.isdigit() and 1 <= int(k) <= len(items):
                return int(k) - 1
            elif k in ("esc", "q", "quit"):
                return None
    finally:
        show_cursor()


def pause(msg="press any key"):
    print(f"\n  {DIM}{msg}{RESET}", end="", flush=True)
    while True:
        k = getkey()
        if k not in ("up", "down"):
            break
    print()


def ask(prompt: str, default: str = "") -> str:
    show_cursor()
    tail = f" {DIM}[{default}]{RESET}" if default else ""
    v = input(f"  {prompt}{tail}: ").strip()
    return v or default


def confirm(title: str, question: str) -> bool:
    idx = select(title, [question, "cancel"], allow_back=True)
    return idx == 0


def box_line(b: dict) -> str:
    age = int(time.time()) - b.get("created_at", 0)
    mins = f"{age // 60}m" if age < 3600 else f"{age // 3600}h"
    return f"{b['address']}   {BOLD}{DIM}{mins}{RESET}  [{b['provider']}]"


def pick_box(title: str) -> dict | None:
    boxes = load_boxes()
    if not boxes:
        clear()
        banner(title)
        print(f"  {YELLOW}no mailboxes yet - create one first{RESET}")
        pause()
        return None
    items = list(boxes.values())
    if len(items) == 1:
        return items[0]
    idx = select(title, [b["address"] for b in items])
    return items[idx] if idx is not None else None


# ----------------------------------------------------------------------- flows
def show_message(cli: Smail, box: dict, msg: dict):
    clear()
    banner("message", "fetching body ...")
    try:
        data = cli.message(box["address"], msg["mid"])
    except SmailError as exc:
        clear()
        banner("message")
        print(f"  {RED}{exc}{RESET}")
        pause()
        return

    clear()
    print(f"  {BOLD}{msg.get('textSubject') or '(no subject)'}{RESET}")
    print(f"  {DIM}{'-' * W}{RESET}")
    print(f"  from  {CYAN}{msg.get('textFrom', '?')}{RESET}")
    print(f"  to    {msg.get('textTo', box['address'])}")
    print(f"  date  {msg.get('textDate', '?')}")
    print(f"  {DIM}{'-' * W}{RESET}\n")

    body = strip_html(data.get("body", ""))
    for line in (body or "(empty body)").splitlines():
        print(f"  {line}")

    atts = data.get("attachments") or []
    if atts:
        print(f"\n  {DIM}{'-' * W}{RESET}")
        print(f"  {BOLD}attachments{RESET}")
        for i, a in enumerate(atts, 1):
            print(f"   {i}. {a.get('name', 'file')}  {DIM}{a.get('size', '')} {a.get('type', '')}{RESET}")

    print()
    actions = ["back"]
    if atts:
        actions.insert(0, "download attachment")
    if body:
        actions.insert(0 if not atts else 1, "save html")

    choice = select("message", actions, sub="what next", allow_back=True)
    if choice is None:
        return
    action = actions[choice]

    if action == "save html":
        fname = re.sub(r"[^\w.-]+", "_", msg.get("textSubject") or "message")[:50] + ".html"
        Path(fname).write_text(data.get("body", ""), encoding="utf-8")
        clear()
        banner("saved")
        print(f"  {GREEN}{Path(fname).resolve()}{RESET}")
        pause()
    elif action == "download attachment":
        ai = select("download", [f"{a.get('name', 'file')}  {a.get('size', '')}" for a in atts])
        if ai is None:
            return
        att = atts[ai]
        fid = att.get("file_id") or att.get("id")
        name = att.get("name") or f"attachment_{fid}"
        clear()
        banner("downloading", name)
        try:
            blob = cli.attachment(box["address"], msg["mid"], fid)
        except SmailError as exc:
            print(f"  {RED}{exc}{RESET}")
            pause()
            return
        Path(name).write_bytes(blob)
        print(f"  {GREEN}{Path(name).resolve()}{RESET}  ({len(blob)} bytes)")
        pause()


def ui_create(cli: Smail):
    domains = ["outlook.com", "gmail.com", "random.com  (random domain)"]
    di = select("create mailbox", domains, sub="pick a domain")
    if di is None:
        return
    domain = domains[di].split("  ")[0]

    clear()
    banner("create mailbox", f"domain: {domain}")
    print(f"  {DIM}generating random address ... 5-15s{RESET}")
    try:
        box = cli.create(domain=domain)
    except SmailError as exc:
        clear()
        banner("create mailbox", "failed")
        print(f"  {RED}{exc}{RESET}")
        pause()
        return

    remember(box)
    clear()
    banner("mailbox ready")
    print(f"  {GREEN}{BOLD}{box['address']}{RESET}\n")
    print(f"  {DIM}key{RESET}   {box['key'][:50]}...")
    print(f"  {DIM}store{RESET} {STORE}")
    pause()


def ui_list():
    boxes = load_boxes()
    clear()
    banner("mailboxes", f"{len(boxes)} saved")
    if not boxes:
        print(f"  {YELLOW}none yet{RESET}")
    for i, b in enumerate(boxes.values(), 1):
        print(f"  {DIM}{i:>2}.{RESET} {box_line(b)}")
    pause()


def message_list(cli: Smail, box: dict, seconds: int) -> bool:
    clear()
    banner("check inbox", f"{box['address']}  -  watching {seconds}s")
    print(f"  {DIM}polling every 2s - ctrl+c to stop{RESET}")
    try:
        msgs, box = cli.wait_for_mail(box, seconds=seconds)
    except KeyboardInterrupt:
        return False
    except SmailError as exc:
        clear()
        banner("check inbox", "failed")
        print(f"  {RED}{exc}{RESET}")
        pause()
        return False

    remember(box)
    if not msgs:
        clear()
        banner("check inbox", box["address"])
        print(f"  {YELLOW}no mail arrived{RESET}")
        pause()
        return False

    labels = []
    for m in msgs:
        subj = (m.get("textSubject") or "(no subject)")[:44]
        frm = (m.get("textFrom") or "?")[:24]
        labels.append(f"{subj}\n        {DIM}{frm}  {m.get('textDate', '')}{RESET}")

    idx = select(f"inbox - {len(msgs)} message(s)", labels,
                 sub=box["address"], allow_back=True)
    if idx is None:
        return False
    show_message(cli, box, msgs[idx])
    return True


def ui_check(cli: Smail):
    box = pick_box("check inbox")
    if not box:
        return
    message_list(cli, box, 60)


def ui_read(cli: Smail):
    box = pick_box("read message")
    if not box:
        return
    message_list(cli, box, 0)


def ui_forget():
    box = pick_box("forget mailbox")
    if not box:
        return
    if confirm("forget mailbox", f"remove {box['address']} from the list?"):
        forget(box["address"])
        clear()
        banner("removed", box["address"])
        pause()


# ------------------------------------------------------------------------ main
MAIN_ITEMS = [
    "create mailbox",
    "list mailboxes",
    "check inbox",
    "read message",
    "forget mailbox",
    "quit",
]


def interactive():
    cli = Smail()
    hide_cursor()
    try:
        while True:
            boxes = load_boxes()
            idx = select(
                "smailpro tempmail",
                MAIN_ITEMS,
                sub=f"{len(boxes)} mailbox(es) saved   -   {STORE.name}",
            )
            if idx is None or MAIN_ITEMS[idx] == "quit":
                break

            action = MAIN_ITEMS[idx]
            if action == "create mailbox":
                ui_create(cli)
            elif action == "list mailboxes":
                ui_list()
            elif action == "check inbox":
                ui_check(cli)
            elif action == "read message":
                ui_read(cli)
            elif action == "forget mailbox":
                ui_forget()
    finally:
        show_cursor()


def main():
    args = sys.argv[1:]
    if not args:
        interactive()
        return

    cmd = args[0].lower()
    if cmd == "new":
        cli = Smail()
        box = cli.create(domain=args[1] if len(args) > 1 else "outlook.com")
        remember(box)
        print(json.dumps(box, indent=2))
    elif cmd == "list":
        for b in load_boxes().values():
            print(b["address"])
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        show_cursor()
        print("\n  bye")
