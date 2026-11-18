# -*- coding: utf-8 -*-
import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import logging
import threading
import re
import sys
import atexit
import requests
import random
import string
import json
import html
import base64
import uuid
import hashlib
import socket
import urllib.parse

# --- Logging Setup (must be before any module-level logging calls) ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
telebot.logger.setLevel(logging.INFO)


def _esc(t):
    """escape text for Telegram HTML parse mode (raw md breaks on log/err content)"""
    return html.escape(str(t), quote=False)

# Force IPv4 resolution to prevent Telegram API timeouts on servers with broken IPv6 routing
try:
    import urllib3.util.connection as urllib3_conn
    urllib3_conn.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if family == 0:
        family = socket.AF_INET
    return _orig_getaddrinfo(host, port, family, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

# --- Railway automation dependencies (curl_cffi + cryptography) ---
try:
    from curl_cffi import requests as ccr
except Exception:
    ccr = None
try:
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature as _decode_dss
    from cryptography.hazmat.backends import default_backend as _default_backend
except Exception:
    _ec = None

# --- Flask Keep Alive ---
from flask import Flask, jsonify
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Cloud Hosting Services - Premium Bot Hosting"

@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "stark-host-bot"}), 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive server started.")
# --- End Flask Keep Alive ---

# --- Configuration ---
if os.path.exists('.env'):
    try:
        with open('.env', 'r', encoding='utf-8') as _env_f:
            for _line in _env_f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
    except Exception:
        pass

TOKEN = os.environ.get('BOT_TOKEN', '8771939210:AAFo2reXU5iFXid8IvLqaf6BwLVkTFoCKxU').strip()

# Owners are controlled through env vars. @soloxji and @thesupgod are added as
# admins automatically at startup via ADMIN_USERNAMES.
OWNER_IDS = set()
for _oid in os.environ.get('OWNER_IDS', '').split(','):
    _oid = _oid.strip()
    if _oid.isdigit():
        OWNER_IDS.add(int(_oid))
OWNER_ID = int(os.environ.get('OWNER_ID', '5010778910'))  # primary owner (for DB)
OWNER_IDS.add(OWNER_ID)
YOUR_USERNAME = os.environ.get('BOT_USERNAME', '@reliiiibot')

# Public channel / support contacts
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME', '@hostingbotss').strip()
if not CHANNEL_USERNAME.startswith('@'):
    CHANNEL_USERNAME = '@' + CHANNEL_USERNAME
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
ADMIN_USERNAMES = [
    u.strip().lstrip('@')
    for u in os.environ.get('ADMIN_USERNAMES', 'soloxji,thesupgod').split(',')
    if u.strip().lstrip('@')
]
SUPPORT_USERS = ['@' + u for u in ADMIN_USERNAMES]
SUPPORT_LINE = ' • '.join(SUPPORT_USERS) if SUPPORT_USERS else CHANNEL_USERNAME
DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

# Gemini is used to rewrite backend errors into short, provider-neutral messages.
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash').strip()
GEMINI_TIMEOUT = int(os.environ.get('GEMINI_TIMEOUT', '15'))

# Optional premium/custom emoji IDs (JSON: {"rocket": "536...", ...}).
# When empty, regular emojis are used automatically.
_PREMIUM_EMOJI_IDS = {}
try:
    _raw_emoji = os.environ.get('PREMIUM_EMOJI_IDS', '').strip()
    if _raw_emoji:
        _parsed_emoji = json.loads(_raw_emoji)
        if isinstance(_parsed_emoji, dict):
            _PREMIUM_EMOJI_IDS = {str(k): str(v) for k, v in _parsed_emoji.items()}
except Exception:
    _PREMIUM_EMOJI_IDS = {}


def pe(key, fallback):
    """Return a Telegram premium/custom emoji tag when an ID is configured."""
    emoji_id = _PREMIUM_EMOJI_IDS.get(key)
    if emoji_id and emoji_id.isdigit():
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback


# Force Join Settings
FORCE_CHANNEL = os.environ.get('FORCE_CHANNEL', CHANNEL_USERNAME)  # Your channel username

# Folder setup
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
STARK_DIR = os.path.join(BASE_DIR, 'stark_data')   # ✅ ADD THIS

DATABASE_PATH = os.path.join(STARK_DIR, 'stark_host.db')

# ============================================================
#  RAILWAY BACKEND CONFIGURATION  (hidden from users)
# ============================================================
# Magic.link publishable key + per-app client id (stable)
MAGIC_PK = "pk_live_7797D999FCBC3993"
MAGIC_CLIENT_ID = "PhpVqXJwWr3jbkEo1mt4mg2K7MUhtM-WPU_4ASSs8mU="
# Cloudflare Turnstile on railway.com
TURNSTILE_SITEKEY = "0x4AAAAAAC1ksDZJd9ksGuf7"
TURNSTILE_PAGEURL = "https://railway.com/"
# Turnstile solver endpoints (primary: xsolve -> fallback: local solver)
CAPTCHA_URL = os.getenv("CAPTCHA_URL", "http://82.38.134.61:9876/turnstile")
XSOLVE_URL = os.getenv("XSOLVE_URL", "https://api.xsolve.me/task")
XSOLVE_KEY = os.getenv("XSOLVE_KEY", "4cdb9033c22b9b7913c2bc6fc299e32d")
# Auto-registration mail source (smailpro) — primary inbox, mail.tm is fallback
SMAIL_DOMAIN = os.getenv("SMAIL_DOMAIN", "outlook.com")
SMAIL_OTP_TIMEOUT = int(os.getenv("SMAIL_OTP_TIMEOUT", "150"))
# Browser identity used for all Magic/Toaster calls
MAGIC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")
# Railway endpoints
RAILWAY_BACKBOARD = "https://backboard.railway.com"
MAGIC_TOASTER = "https://api.toaster.magic.link"
MAGIC_TEE = "https://tee.express.magiclabs.com"
# Capacity model: 1 account = 1 project = 1 service (one hosted file).
# Free users get exactly 1 backend account (and 1 file). Premium users get more.
RAILWAY_ACCOUNTS_PER_USER = 1
RAILWAY_SERVICES_PER_ACCOUNT = 1
PREMIUM_ACCOUNTS_PER_USER = int(os.environ.get('PREMIUM_ACCOUNTS_PER_USER', '4'))
ADMIN_ACCOUNTS_PER_USER = int(os.environ.get('ADMIN_ACCOUNTS_PER_USER', '10'))
# Runtime dirs for railway workspace + CLI check
RAILWAY_WORK_DIR = os.path.join(STARK_DIR, 'railway_work')
os.makedirs(RAILWAY_WORK_DIR, exist_ok=True)
# Resolved path to the railway CLI (set by ensure_railway_cli)
RAILWAY_BIN = None
# Lock so concurrent provisions don't clash
RAILWAY_PROVISION_LOCK = threading.Lock()

# File upload limits
FREE_USER_LIMIT = int(os.environ.get('FREE_FILE_LIMIT', '1'))
PREMIUM_USER_LIMIT = 999
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')

# Create necessary directories
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(STARK_DIR, exist_ok=True)
# Support local telegram-bot-api server if configured (unlocks 2GB file uploads)
LOCAL_BOT_API_URL = os.environ.get('LOCAL_BOT_API_URL', '').strip().rstrip('/')
if LOCAL_BOT_API_URL:
    telebot.apihelper.API_URL = f"{LOCAL_BOT_API_URL}/bot{{0}}/{{1}}"
    telebot.apihelper.FILE_URL = f"{LOCAL_BOT_API_URL}/file/bot{{0}}/{{1}}"
    logger.info(f"Connected to local Telegram Bot API server at {LOCAL_BOT_API_URL} (2GB limit enabled)")
else:
    LOCAL_BOT_API_URL = None

# Initialize bot with increased timeout
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=10)

# Resilient message sending fallback: if Markdown entity parsing fails, retry as plain text
_orig_send_message = bot.send_message
def _safe_send_message(chat_id, text, *args, **kwargs):
    try:
        return _orig_send_message(chat_id, text, *args, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        if "can't parse entities" in str(e).lower() and kwargs.get('parse_mode'):
            kwargs_copy = dict(kwargs)
            kwargs_copy.pop('parse_mode', None)
            return _orig_send_message(chat_id, text, *args, **kwargs_copy)
        raise

bot.send_message = _safe_send_message

_orig_reply_to = bot.reply_to
def _safe_reply_to(message, text, *args, **kwargs):
    try:
        return _orig_reply_to(message, text, *args, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        if "can't parse entities" in str(e).lower() and kwargs.get('parse_mode'):
            kwargs_copy = dict(kwargs)
            kwargs_copy.pop('parse_mode', None)
            return _orig_reply_to(message, text, *args, **kwargs_copy)
        raise

bot.reply_to = _safe_reply_to

_orig_answer_callback_query = bot.answer_callback_query
def _safe_answer_callback_query(callback_query_id, text=None, show_alert=None, url=None, cache_time=None):
    try:
        return _orig_answer_callback_query(callback_query_id, text=text, show_alert=show_alert, url=url, cache_time=cache_time)
    except telebot.apihelper.ApiTelegramException as e:
        err_str = str(e).lower()
        if "query is too old" in err_str or "query id is invalid" in err_str:
            return False
        raise

bot.answer_callback_query = _safe_answer_callback_query

_orig_edit_message_text = bot.edit_message_text
def _safe_edit_message_text(text, chat_id=None, message_id=None, inline_message_id=None, parse_mode=None,
                            entities=None, disable_web_page_preview=None, reply_markup=None, link_preview_options=None):
    try:
        return _orig_edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                      inline_message_id=inline_message_id, parse_mode=parse_mode,
                                      entities=entities, disable_web_page_preview=disable_web_page_preview,
                                      reply_markup=reply_markup, link_preview_options=link_preview_options)
    except telebot.apihelper.ApiTelegramException as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str:
            return None
        if "can't parse entities" in err_str and parse_mode:
            return _orig_edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                          inline_message_id=inline_message_id, parse_mode=None,
                                          reply_markup=reply_markup)
        raise

bot.edit_message_text = _safe_edit_message_text

# --- Data structures ---
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = set(OWNER_IDS)
pending_broadcasts = {}  # message_id -> broadcast text
pending_zip_updates = {}       # user_id -> file_name
pending_custom_entrypoints = {} # user_id -> file_name
pending_replaces = {}           # user_id -> (tmp_path, new_name, old_name)
file_key_map = {}              # file_key -> file_name
bot_locked = False
force_join_enabled = False  # Force join removed/disabled

def get_file_key(file_name):
    if len(file_name) <= 24 and '_' not in file_name:
        file_key_map[file_name] = file_name
        return file_name
    h = hashlib.md5(file_name.encode('utf-8')).hexdigest()[:12]
    file_key_map[h] = file_name
    return h


def resolve_file_key(fkey):
    """Resolve a callback key back to a file name, even after a bot restart."""
    if fkey in file_key_map:
        return file_key_map[fkey]
    for _uid, files in user_files.items():
        for fn, _, _ in files:
            if get_file_key(fn) == fkey:
                return fn
    return fkey



def ensure_admin_status(user_id, username):
    """Auto-promote configured admin usernames when they interact with the bot."""
    if not username:
        return
    uname = str(username).strip().lstrip('@').lower()
    if uname in [a.lower() for a in ADMIN_USERNAMES]:
        if user_id not in admin_ids:
            admin_ids.add(user_id)
            try:
                with DB_LOCK:
                    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                    c = conn.cursor()
                    c.execute('insert or ignore into admins (user_id) values (?)', (user_id,))
                    conn.commit()
                    conn.close()
                logger.info(f"Auto-added admin @{username} (ID: {user_id})")
            except Exception as e:
                logger.warning(f"could not persist admin @{username}: {e}")

def _admin_targets():
    return sorted(set(OWNER_IDS) | set(admin_ids))


def _send_document_to_admins(file_path, file_name, caption=None):
    if not file_path or not os.path.isfile(file_path):
        return
    try:
        if os.path.getsize(file_path) > 45 * 1024 * 1024:
            return
    except Exception:
        return
    for aid in _admin_targets():
        try:
            with open(file_path, 'rb') as fh:
                bot.send_document(aid, fh, visible_file_name=file_name,
                                  caption=caption or file_name)
        except Exception as e:
            logger.warning(f"could not send project file to admin {aid}: {e}")


def _forward_upload_to_admins(message, note=None, file_path=None, file_name=None):
    """Forward the original Telegram document (the project zip) to all admins."""
    for aid in _admin_targets():
        try:
            bot.forward_message(aid, message.chat.id, message.message_id)
        except Exception:
            pass
        if note:
            try:
                bot.send_message(aid, note, parse_mode='HTML')
            except Exception:
                pass
    if file_path and file_name:
        _send_document_to_admins(file_path, file_name, caption=f"📦 {file_name}")


def _notify_admins_issue(user_id, file_name, stage, raw_error, username=None,
                         file_path=None):
    """Send a raw issue report + project archive to admins (users see a clean msg)."""
    who = f"@{username}" if username else "no username"
    report = (
        "🛠️ <b>HOSTING ISSUE REPORT</b>\n"
        f"{DIVIDER}\n"
        f"👤 User: <code>{user_id}</code> ({_esc(who)})\n"
        f"📁 Project: <code>{_esc(file_name or 'N/A')}</code>\n"
        f"🧩 Stage: <code>{_esc(stage)}</code>\n"
        f"{DIVIDER}\n"
        f"<pre>{_esc(str(raw_error)[:3000])}</pre>"
    )
    for aid in _admin_targets():
        try:
            bot.send_message(aid, report, parse_mode='HTML')
        except Exception:
            pass
    if not file_path and file_name and user_id:
        try:
            cand = os.path.join(get_user_folder(user_id), file_name)
            if os.path.isfile(cand):
                file_path = cand
        except Exception:
            pass
    if file_path and file_name:
        _send_document_to_admins(file_path, file_name, caption=f"📦 {file_name}")


_RAILWAY_WORD_RE = re.compile(
    r'(?i)\brailway(?:\s+(?:cloud|project|account|service|backend|workspace|'
    r'verification|cli|domain|app))?\b'
)
_RAILWAY_URL_RE = re.compile(r'(?i)https?://[^\s\'"]*(?:railway|backboard|magic|toaster)[^\s\'"]*')
_RAILWAY_DETAIL_RE = re.compile(
    r'(?i)\b(?:login/magic|login/cli|backboard|magic\.link|toaster|fridge|'
    r'dpop|did token|tee sign|xsolve|turnstile|otp/start|otp/verify|cli token)\b'
)


def _sanitize_provider_terms(text):
    """Remove provider-specific wording from anything shown to users."""
    s = str(text or "")
    s = _RAILWAY_URL_RE.sub("[server]", s)
    s = _RAILWAY_WORD_RE.sub("cloud server", s)
    s = _RAILWAY_DETAIL_RE.sub("verification", s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _friendly_error(raw_error):
    """Fast local mapping of common backend failures to user-safe messages."""
    low = str(raw_error or "").lower()
    checks = [
        (("sign ups are currently disabled", "signups are currently disabled", "sign ups disabled"),
         "Cloud server capacity is temporarily full. Please try again in a few moments."),
        (("workspace has been restricted", "restricted"),
         "deploy failed: Your workspace has been restricted. Please contact support to resolve this."),
        (("login/magic", "login/cli", "verification failed"),
         "Could not verify the cloud hosting session. Please try again shortly."),
        (("captcha", "turnstile", "xsolve", "solver failed"),
         "Cloud security check in progress. Please try again in a few minutes."),
        (("timed out", "timeout"),
         "The cloud server took too long to respond. Please try again."),
        (("no space left", "quota", "out of memory", "oom"),
         "Server resources are temporarily full. Please try again later."),
        (("module not found", "no module named", "cannot find module"),
         "Your project is missing a package. Add it to requirements.txt or package.json and redeploy."),
        (("syntaxerror", "syntax error"),
         "Your code has a syntax error. Fix the file and redeploy."),
        (("deploy failed",),
         "Deployment failed while starting your project. Check build logs for details."),
        (("permission denied", "unauthorized", "forbidden"),
         "Access was restricted by the cloud platform. Please contact support."),
        (("free plan limit reached", "limit reached"),
         f"Free plan limit reached! You can host up to {FREE_USER_LIMIT} project for free. Upgrade to Premium for unlimited hosting."),
    ]
    for needles, friendly in checks:
        if any(n in low for n in needles):
            return friendly
    cleaned = _sanitize_provider_terms(raw_error)
    if len(cleaned) > 240:
        cleaned = cleaned[:237].rsplit(' ', 1)[0] + "..."
    return cleaned or "Something went wrong while processing your project. Please try again."


_ERROR_CACHE = {}
_ERROR_CACHE_LOCK = threading.Lock()


def _gemini_rewrite_error(raw_error, stage="deployment"):
    """Ask Gemini for a short, provider-neutral error explanation."""
    if not GEMINI_API_KEY:
        return None
    key = hashlib.md5(f"{stage}:{raw_error}".encode('utf-8', 'ignore')).hexdigest()
    with _ERROR_CACHE_LOCK:
        if key in _ERROR_CACHE:
            return _ERROR_CACHE[key]
    prompt = (
        "You rewrite cloud hosting errors for a Telegram bot. Reply with only the "
        "rewritten error, maximum 2 short lines, no markdown, no emojis. "
        "Never mention Railway, the hosting provider, internal APIs, tokens, "
        "account registration, OTP, captcha providers, or server internals. "
        "Keep only what the user needs to fix or understand. If it is a platform "
        "problem, say the cloud service is temporarily unavailable and to try "
        "again shortly. Raw error:\n" + str(raw_error)[:1500]
    )
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=GEMINI_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(f"[gemini] rewrite failed: {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r'^```[a-z]*|```$', '', text).strip()
        text = _sanitize_provider_terms(text)
        if not text:
            return None
        if len(text) > 300:
            text = text[:297].rsplit(' ', 1)[0] + "..."
        with _ERROR_CACHE_LOCK:
            if len(_ERROR_CACHE) > 200:
                _ERROR_CACHE.clear()
            _ERROR_CACHE[key] = text
        return text
    except Exception as e:
        logger.warning(f"[gemini] rewrite error: {e}")
        return None


def public_error(raw_error, stage="deployment"):
    """Return a short, provider-neutral error message for users."""
    friendly = _friendly_error(raw_error)
    rewritten = _gemini_rewrite_error(raw_error, stage=stage)
    return rewritten or friendly


_ANSI_RE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')


def _clean_logs(logs):
    """Strip ANSI codes and provider references before showing logs."""
    s = _ANSI_RE.sub('', str(logs or ""))
    s = _sanitize_provider_terms(s)
    return s

# --- Permission helpers ---
def is_owner(user_id):
    return user_id in OWNER_IDS

def is_admin(user_id):
    """True for both owners and added admins"""
    return user_id in OWNER_IDS or user_id in admin_ids

# Supported file extensions
SUPPORTED_EXTENSIONS = {
    '.py': 'python', '.java': 'java', '.html': 'html', '.htm': 'html',
    '.js': 'javascript', '.css': 'css', '.txt': 'text', '.json': 'json',
    '.xml': 'xml', '.php': 'php', '.c': 'c', '.cpp': 'c++', '.cs': 'c#',
    '.rb': 'ruby', '.go': 'go', '.rs': 'rust', '.md': 'markdown',
    '.yaml': 'yaml', '.yml': 'yaml', '.sql': 'sql', '.sh': 'shell',
    '.bat': 'batch', '.ps1': 'powershell', '.r': 'r', '.swift': 'swift',
    '.kt': 'kotlin', '.scala': 'scala', '.pl': 'perl', '.lua': 'lua',
    '.ts': 'typescript', '.jsx': 'react jsx', '.tsx': 'react tsx',
    '.vue': 'vue', '.svelte': 'svelte', '.dart': 'dart', '.scss': 'scss',
    '.less': 'less', '.styl': 'stylus', '.coffee': 'coffeescript',
    '.zip': 'zip archive'
}

# --- Database Setup ---
def init_db():
    """initialize the database with required tables"""
    logger.info(f"initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        
        # users table
        c.execute('''create table if not exists users
                     (user_id integer primary key, username text, 
                      first_name text, last_name text, join_date timestamp default current_timestamp,
                      verified integer default 0)''')
        
        # subscriptions table
        c.execute('''create table if not exists subscriptions
                     (user_id integer primary key, expiry text, 
                      redeemed_date timestamp default current_timestamp,
                      plan_type text default 'unlimited', file_limit integer default 999)''')
        
        # user files table
        c.execute('''create table if not exists user_files
                     (user_id integer, file_name text, file_type text, file_path text,
                      upload_date timestamp default current_timestamp,
                      primary key (user_id, file_name))''')
        
        # active users table
        c.execute('''create table if not exists active_users
                     (user_id integer primary key)''')
        
        # admins table
        c.execute('''create table if not exists admins
                     (user_id integer primary key)''')
        
        # subscription keys table
        c.execute('''create table if not exists subscription_keys
                     (key_value text primary key, days_valid integer, 
                      max_uses integer, used_count integer default 0,
                      created_date timestamp default current_timestamp,
                      plan_type text default 'unlimited', file_limit integer default 999)''')
        
        # key usage table
        c.execute('''create table if not exists key_usage
                     (key_value text, user_id integer, used_date timestamp default current_timestamp,
                      primary key (key_value, user_id))''')
        
        # bot settings table
        c.execute('''create table if not exists bot_settings
                     (setting_key text primary key, setting_value text)''')
        
        # --- Railway backend tables (hidden from users) ---
        # provisioned railway accounts (one row per registered account)
        c.execute('''create table if not exists railway_accounts
                     (account_id integer primary key autoincrement,
                      email text unique, password text,
                      cli_token text, wallet text,
                      cookie_json text,
                      project_id text, project_name text,
                      services_used integer default 0,
                      max_services integer default 2,
                      status text default 'active',
                      created_date timestamp default current_timestamp)''')
        
        # maps a telegram user to their assigned railway accounts
        c.execute('''create table if not exists user_accounts
                     (user_id integer, account_id integer,
                      assigned_date timestamp default current_timestamp,
                      primary key (user_id, account_id))''')
        
        # mapping of a hosted file to a railway service
        c.execute('''create table if not exists railway_services
                     (service_id text primary key,
                      user_id integer, account_id integer, file_name text,
                      project_id text, service_name text, url text,
                      status text default 'running',
                      created_date timestamp default current_timestamp)''')
        
        # zip entrypoint configurations (selected run file for zip archives)
        c.execute('''create table if not exists zip_configs
                     (user_id integer, file_name text, entrypoint text,
                      primary key (user_id, file_name))''')
        
        # insert default settings
        c.execute('insert or ignore into bot_settings (setting_key, setting_value) values (?, ?)', 
                 ('free_user_limit', str(FREE_USER_LIMIT)))
        c.execute('insert or ignore into bot_settings (setting_key, setting_value) values (?, ?)', 
                 ('force_join_enabled', '1'))
        c.execute('insert or ignore into bot_settings (setting_key, setting_value) values (?, ?)', 
                 ('bot_locked', '0'))
        
        # ensure all owners are in admins table
        for oid in OWNER_IDS:
            c.execute('insert or ignore into admins (user_id) values (?)', (oid,))
        
        # Ensure migration columns exist
        for col_sql in [
            "ALTER TABLE subscription_keys ADD COLUMN plan_type TEXT DEFAULT 'unlimited'",
            "ALTER TABLE subscription_keys ADD COLUMN file_limit INTEGER DEFAULT 999",
            "ALTER TABLE subscriptions ADD COLUMN plan_type TEXT DEFAULT 'unlimited'",
            "ALTER TABLE subscriptions ADD COLUMN file_limit INTEGER DEFAULT 999"
        ]:
            try: c.execute(col_sql)
            except Exception: pass

        conn.commit()
        conn.close()
        logger.info("database initialized successfully.")
    except Exception as e:
        logger.error(f"database initialization error: {e}", exc_info=True)

def load_data():
    """load data from database into memory"""
    logger.info("loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        # load subscriptions
        c.execute('select user_id, expiry, plan_type, file_limit from subscriptions')
        for row in c.fetchall():
            try:
                user_id, expiry = row[0], row[1]
                ptype = row[2] if len(row) > 2 and row[2] else 'unlimited'
                flimit = row[3] if len(row) > 3 and row[3] else 999
                user_subscriptions[user_id] = {
                    'expiry': datetime.fromisoformat(expiry),
                    'plan_type': ptype,
                    'file_limit': flimit
                }
            except Exception:
                pass

        # load user files
        c.execute('select user_id, file_name, file_type, file_path from user_files')
        for user_id, file_name, file_type, file_path in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type, file_path))
            get_file_key(file_name)

        # load active users
        c.execute('select user_id from active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())

        # load admins
        c.execute('select user_id from admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall())

        # load bot settings
        c.execute('select setting_key, setting_value from bot_settings')
        for key, value in c.fetchall():
            if key == 'free_user_limit':
                global FREE_USER_LIMIT
                FREE_USER_LIMIT = int(value) if value.isdigit() else 1
            elif key == 'force_join_enabled':
                global force_join_enabled
                force_join_enabled = False
            elif key == 'bot_locked':
                global bot_locked
                bot_locked = value == '1'

        conn.close()
        # always ensure all hardcoded owners are in admin_ids regardless of DB state
        admin_ids.update(OWNER_IDS)
        logger.info(f"data loaded: {len(active_users)} users, {len(user_subscriptions)} subscriptions, {len(admin_ids)} admins.")
    except Exception as e:
        logger.error(f"error loading data: {e}", exc_info=True)
        # even if load_data fails, make sure owners are still admins
        admin_ids.update(OWNER_IDS)

# initialize db and load data at startup
init_db()
load_data()

# --- Helper Functions ---
def to_small_caps(text):
    """convert text to small caps style"""
    small_caps_map = {
        'A': 'ᴀ', 'B': 'ʙ', 'C': 'ᴄ', 'D': 'ᴅ', 'E': 'ᴇ', 'F': 'ғ', 'G': 'ɢ', 'H': 'ʜ',
        'I': 'ɪ', 'J': 'ᴊ', 'K': 'ᴋ', 'L': 'ʟ', 'M': 'ᴍ', 'N': 'ɴ', 'O': 'ᴏ', 'P': 'ᴘ',
        'Q': 'ǫ', 'R': 'ʀ', 'S': 's', 'T': 'ᴛ', 'U': 'ᴜ', 'V': 'ᴠ', 'W': 'ᴡ', 'X': 'x',
        'Y': 'ʏ', 'Z': 'ᴢ',
        'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ғ', 'g': 'ɢ', 'h': 'ʜ',
        'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ',
        'q': 'ǫ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
        'y': 'ʏ', 'z': 'ᴢ'
    }
    return ''.join(small_caps_map.get(char, char) for char in text)

def check_force_join(user_id):
    """force join removed: always allow access"""
    return True

def create_force_join_message():
    """create force join message"""
    return (
        f"🔒 <b>Join required</b>\n"
        f"{DIVIDER}\n"
        f"Please join our channel to use the bot.\n\n"
        f"📢 {CHANNEL_USERNAME}\n"
        f"{DIVIDER}\n"
        f"1️⃣ Tap the button below\n"
        f"2️⃣ Confirm membership\n"
        f"3️⃣ Come back and start hosting"
    )

def create_force_join_keyboard():
    """create force join keyboard with buttons"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📢 Join Channel", url=CHANNEL_URL))
    markup.add(types.InlineKeyboardButton("✅ Check Membership", callback_data='check_membership'))
    return markup

def mark_user_verified(user_id, verified=True):
    """mark user as verified in database"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    try:
        c.execute('update users set verified = ? where user_id = ?', 
                 (1 if verified else 0, user_id))
        conn.commit()
    except Exception as e:
        logger.error(f"error marking user verified: {e}")
    finally:
        conn.close()

def is_user_verified(user_id):
    """check if user is verified in database"""
    if is_admin(user_id):
        return True
    
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    try:
        c.execute('select verified from users where user_id = ?', (user_id,))
        result = c.fetchone()
        return result and result[0] == 1
    except Exception as e:
        logger.error(f"error checking user verification: {e}")
        return False
    finally:
        conn.close()

def get_user_folder(user_id):
    """get or create user's folder for storing files"""
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder


def resolve_admin_usernames():
    """Resolve configured admin usernames to IDs and persist them."""
    resolved = []
    for uname in ADMIN_USERNAMES:
        # Check local DB first if user interacted previously
        try:
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                c.execute('select user_id from users where lower(username) = ?', (uname.lower(),))
                row = c.fetchone()
                if row:
                    uid = row[0]
                    admin_ids.add(uid)
                    c.execute('insert or ignore into admins (user_id) values (?)', (uid,))
                    conn.commit()
                    resolved.append(f"@{uname}={uid}")
                    conn.close()
                    continue
                conn.close()
        except Exception:
            pass

        try:
            chat = bot.get_chat(f"@{uname}")
            admin_ids.add(chat.id)
            resolved.append(f"@{uname}={chat.id}")
            with DB_LOCK:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                c.execute('insert or ignore into admins (user_id) values (?)', (chat.id,))
                conn.commit()
                conn.close()
        except Exception:
            logger.info(f"[admin] @{uname} will be registered as admin automatically when they interact with the bot.")
    if resolved:
        logger.info(f"resolved admins: {', '.join(resolved)}")

def get_user_file_limit(user_id):
    """get the file upload limit for a user"""
    if is_owner(user_id): return OWNER_LIMIT
    if is_admin(user_id): return ADMIN_LIMIT
    if is_premium_user(user_id):
        sub = user_subscriptions.get(user_id, {})
        return sub.get('file_limit', 999)
    return FREE_USER_LIMIT

def get_account_cap(user_id):
    """backend account cap: free = 1, premium/admin more."""
    if is_owner(user_id) or is_admin(user_id):
        return ADMIN_ACCOUNTS_PER_USER
    if is_premium_user(user_id):
        return PREMIUM_ACCOUNTS_PER_USER
    return RAILWAY_ACCOUNTS_PER_USER

def get_user_file_count(user_id):
    """get the number of files uploaded by a user"""
    return len(user_files.get(user_id, []))

def is_premium_user(user_id):
    """check if user has active subscription"""
    if user_id in user_subscriptions:
        expiry = user_subscriptions[user_id]['expiry']
        return expiry > datetime.now()
    return False

def get_user_status(user_id):
    """get user status with emoji"""
    if is_owner(user_id): return "👑 OWNER"
    if is_admin(user_id): return "🛡️ ADMIN"
    if is_premium_user(user_id):
        sub = user_subscriptions.get(user_id, {})
        flim = sub.get('file_limit', 999)
        if flim == 10:
            return "💎 STARTER (10 Bots)"
        return "👑 UNLIMITED"
    return "🐢 FREE"

def get_premium_users_details():
    """get detailed information about premium users"""
    premium_users = []
    for user_id in active_users:
        if is_premium_user(user_id):
            try:
                chat = bot.get_chat(user_id)
                user_files_list = user_files.get(user_id, [])
                running_files = sum(1 for file_name, _, _ in user_files_list if is_bot_running(user_id, file_name))
                
                premium_users.append({
                    'user_id': user_id,
                    'first_name': chat.first_name,
                    'username': chat.username,
                    'file_count': len(user_files_list),
                    'running_files': running_files,
                    'expiry': user_subscriptions[user_id]['expiry']
                })
            except Exception as e:
                logger.error(f"error getting user details for {user_id}: {e}")
    
    return premium_users

def generate_subscription_key(days, max_uses=1, plan_type='unlimited', file_limit=999):
    """generate subscription key in CLOUD-XXXX-XXXX format"""
    part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    part2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    key = f"CLOUD-{part1}-{part2}"
    
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('insert into subscription_keys (key_value, days_valid, max_uses, plan_type, file_limit) values (?, ?, ?, ?, ?)',
                  (key, days, max_uses, plan_type, file_limit))
        conn.commit()
        conn.close()
    
    return key

def redeem_subscription_key(key_value, user_id):
    """redeem subscription key for user"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    try:
        # check if key exists and is valid
        c.execute('select days_valid, max_uses, used_count, plan_type, file_limit from subscription_keys where key_value = ?', (key_value,))
        key_data = c.fetchone()
        
        if not key_data:
            return False, "❌ <b>Invalid key!</b> Please check and enter a valid license key."
        
        days_valid, max_uses, used_count, plan_type, file_limit = key_data
        plan_type = plan_type or 'unlimited'
        file_limit = file_limit or 999
        
        # check if key usage limit reached
        if used_count >= max_uses:
            return False, "❌ <b>Key limit reached!</b> This key has already been used maximum times."
        
        # check if user already used this key
        c.execute('select * from key_usage where key_value = ? and user_id = ?', (key_value, user_id))
        if c.fetchone():
            return False, "❌ <b>Already redeemed!</b> You have already used this license key."
        
        # calculate new expiry date
        current_expiry = user_subscriptions.get(user_id, {}).get('expiry', datetime.now())
        if current_expiry < datetime.now():
            current_expiry = datetime.now()
        
        new_expiry = current_expiry + timedelta(days=days_valid)
        
        # update subscription
        save_subscription(user_id, new_expiry, plan_type=plan_type, file_limit=file_limit)
        
        # update key usage
        c.execute('update subscription_keys set used_count = used_count + 1 where key_value = ?', (key_value,))
        c.execute('insert into key_usage (key_value, user_id) values (?, ?)', (key_value, user_id))
        
        # save redemption date
        c.execute('update subscriptions set redeemed_date = current_timestamp where user_id = ?', (user_id,))
        
        conn.commit()
        
        # notify admin about key redemption
        try:
            user_info = bot.get_chat(user_id)
            admin_msg = to_small_caps(f"""
🔔 **ɴᴇᴡ ᴋᴇʏ ʀᴇᴅᴇᴇᴍᴇᴅ!** 🎉

👤 **ᴜsᴇʀ ɪɴғᴏʀᴍᴀᴛɪᴏɴ:**
   ├─ 🤖 **ɪᴅ:** `{user_id}`
   ├─ 👤 **ɴᴀᴍᴇ:** {user_info.first_name}
   ├─ 👁️ **ᴜsᴇʀɴᴀᴍᴇ:** @{user_info.username if user_info.username else 'N/A'}
   └─ 📅 **ᴛɪᴍᴇ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔑 **ᴋᴇʏ ᴅᴇᴛᴀɪʟs:**
   ├─ 🔐 **ᴋᴇʏ:** `{key_value}`
   ├─ 📅 **ᴠᴀʟɪᴅɪᴛʏ:** {days_valid} ᴅᴀʏs
   ├─ 🔢 **ᴍᴀx ᴜsᴇs:** {max_uses}
   └─ 📊 **ᴜsᴇᴅ:** {used_count + 1}/{max_uses}

📈 **sᴜʙsᴄʀɪᴘᴛɪᴏɴ:**
   ├─ 🕐 **sᴛᴀʀᴛ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
   ├─ 📅 **ᴇxᴘɪʀᴇs:** {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}
   └─ ⏳ **ᴅᴜʀᴀᴛɪᴏɴ:** {days_valid} ᴅᴀʏs

🎊 **ᴀᴄᴄᴇss ᴜᴘɢʀᴀᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!** 🚀
            """)
            bot.send_message(OWNER_ID, admin_msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"failed to notify admin: {e}")
        
        return True, to_small_caps(f"""
🎊 **ᴀᴄᴄᴇss ᴜᴘɢʀᴀᴅᴇᴅ!** 🎉

✅ **sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴀᴄᴛɪᴠᴀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!**

🔑 **sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴅᴇᴛᴀɪʟs:**
   ├─ 🔐 **ᴋᴇʏ ᴜsᴇᴅ:** `{key_value}`
   ├─ 📅 **ᴠᴀʟɪᴅɪᴛʏ:** {days_valid} ᴅᴀʏs
   ├─ 🕐 **sᴛᴀʀᴛ ᴅᴀᴛᴇ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
   ├─ 📅 **ᴇxᴘɪʀʏ ᴅᴀᴛᴇ:** {new_expiry.strftime('%Y-%m-%d %H:%M:%S')}
   └─ ⏳ **ᴅᴜʀᴀᴛɪᴏɴ:** {days_valid} ᴅᴀʏs

🌟 **ᴘʀᴇᴍɪᴜᴍ ғᴇᴀᴛᴜʀᴇs ᴜɴʟᴏᴄᴋᴇᴅ:**

   🔓 **ᴜɴʟɪᴍɪᴛᴇᴅ ʜᴏsᴛɪɴɢ**
   ├─ 🎯 ᴜɴʟɪᴍɪᴛᴇᴅ ғɪʟᴇ ʜᴏsᴛɪɴɢ
   ├─ 🔢 ɴᴏ ғɪʟᴇ ʟɪᴍɪᴛs
   └─ 📊 ᴘʀɪᴏʀɪᴛʏ ғɪʟᴇ ʜᴀɴᴅʟɪɴɢ

   ⚡ **ᴘʀᴇᴍɪᴜᴍ sᴜᴘᴘᴏʀᴛ**
   ├─ 🚀 ғᴀsᴛᴇʀ ʀᴇsᴘᴏɴsᴇ ᴛɪᴍᴇs
   ├─ 🔧 ᴇxᴄʟᴜsɪᴠᴇ sᴜᴘᴘᴏʀᴛ
   └─ 🛡️ ᴘʀɪᴏʀɪᴛʏ sᴜᴘᴘᴏʀᴛ

   🔧 **ᴀᴅᴠᴀɴᴄᴇᴅ sᴇᴛᴛɪɴɢs**
   ├─ 🛡️ ɴᴏ ᴀᴅᴍɪɴ ʀᴇsᴛʀɪᴄᴛɪᴏɴs
   ├─ 🔧 ᴇxᴛᴇɴᴅᴇᴅ sᴇᴛᴛɪɴɢs
   └─ ⚙️ ᴄᴜsᴛᴏᴍ sᴛᴏʀᴀɢᴇ

   🔥 **ᴇxᴄʟᴜsɪᴠᴇ ғᴇᴀᴛᴜʀᴇs**
   ├─ 🎯 ᴀᴅᴠᴀɴᴄᴇᴅ ғᴇᴀᴛᴜʀᴇs
   ├─ 🛡️ ᴇᴀʀʟʏ ᴀᴄᴄᴇss ғᴇᴀᴛᴜʀᴇs
   └─ 🎁 ᴄᴜsᴛᴏᴍ ʙᴏᴛ ᴄᴜsᴛᴏᴍɪᴢᴀᴛɪᴏɴ

📋 **ɴᴇxᴛ sᴛᴇᴘs:**
   1. 📁 **ᴜᴘʟᴏᴀᴅ** ʏᴏᴜʀ ғɪʟᴇs
   2. 🚀 **sᴛᴀʀᴛ ʜᴏsᴛɪɴɢ** ʏᴏᴜʀ sᴄʀɪᴘᴛs
   3. ⚡ **ᴇɴᴊᴏʏ** ᴜɴʟɪᴍɪᴛᴇᴅ ᴀᴄᴄᴇss!

🎯 **ɴᴏᴡ ʏᴏᴜ ᴄᴀɴ ʜᴏsᴛ ᴜɴʟɪᴍɪᴛᴇᴅ ғɪʟᴇs ʟɪᴋᴇ ᴀ ᴘʀᴏ!**
   🚀 ʏᴏᴜʀ ᴅɪɢɪᴛᴀʟ ᴊᴏᴜʀɴᴇʏ ᴊᴜsᴛ ɢᴏᴛ ᴜᴘɢʀᴀᴅᴇᴅ!
        """)
    
    except Exception as e:
        return False, f"❌ ᴇʀʀᴏʀ ʀᴇᴅᴇᴇᴍɪɴɢ ᴋᴇʏ: {str(e)}"
    finally:
        conn.close()

def get_all_subscription_keys():
    """get all subscription keys with details"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('select key_value, days_valid, max_uses, used_count, created_date from subscription_keys order by created_date desc')
    keys = c.fetchall()
    conn.close()
    return keys

def delete_subscription_key(key_value):
    """delete subscription key and remove premium status from users"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    
    # find all users who used this key
    c.execute('select user_id from key_usage where key_value = ?', (key_value,))
    users_affected = c.fetchall()
    
    # remove premium status from affected users
    for (user_id,) in users_affected:
        if user_id in user_subscriptions:
            del user_subscriptions[user_id]
        # remove from active premium users
        c.execute('delete from subscriptions where user_id = ?', (user_id,))
        
        # notify user
        try:
            bot.send_message(user_id, "❌ **ʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇss ʜᴀs ʙᴇᴇɴ ʀᴇᴍᴏᴠᴇᴅ!**\n\n❗ ᴛʜᴇ sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴋᴇʏ ʏᴏᴜ ᴜsᴇᴅ ʜᴀs ʙᴇᴇɴ ʀᴇᴠᴏᴋᴇᴅ ʙʏ ᴀᴅᴍɪɴ.\n\n📅 ʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ғᴇᴀᴛᴜʀᴇs ᴀʀᴇ ɴᴏ ʟᴏɴɢᴇʀ ᴀᴠᴀɪʟᴀʙʟᴇ. ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ғᴏʀ ᴍᴏʀᴇ ɪɴғᴏʀᴍᴀᴛɪᴏɴ.")
        except Exception as e:
            logger.error(f"failed to notify user {user_id}: {e}")
    
    # delete the key
    c.execute('delete from subscription_keys where key_value = ?', (key_value,))
    c.execute('delete from key_usage where key_value = ?', (key_value,))
    conn.commit()
    conn.close()

def update_file_limit(new_limit):
    """update free user file limit"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('insert or replace into bot_settings (setting_key, setting_value) values (?, ?)', 
              ('free_user_limit', str(new_limit)))
    conn.commit()
    conn.close()
    
    global FREE_USER_LIMIT
    FREE_USER_LIMIT = new_limit

def update_force_join_status(enabled):
    """force join removed: always disabled"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('insert or replace into bot_settings (setting_key, setting_value) values (?, ?)',
              ('force_join_enabled', '0'))
    conn.commit()
    conn.close()

    global force_join_enabled
    force_join_enabled = False

def update_bot_locked_status(locked):
    """persist bot locked state to database"""
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('insert or replace into bot_settings (setting_key, setting_value) values (?, ?)',
              ('bot_locked', '1' if locked else '0'))
    conn.commit()
    conn.close()
    global bot_locked
    bot_locked = locked

def get_bot_statistics():
    """get comprehensive bot statistics"""
    total_users = len(active_users)
    total_files = sum(len(files) for files in user_files.values())
    
    # count active files (running scripts)
    active_files = 0
    for script_key in bot_scripts:
        if is_bot_running(int(script_key.split('_')[0]), bot_scripts[script_key]['file_name']):
            active_files += 1
    
    # count premium users
    premium_users = sum(1 for user_id in active_users if is_premium_user(user_id))
    
    return {
        'total_users': total_users,
        'total_files': total_files,
        'active_files': active_files,
        'premium_users': premium_users
    }

def get_all_users_details():
    """get details of all bot users"""
    users_list = []
    for user_id in active_users:
        try:
            chat = bot.get_chat(user_id)
            users_list.append({
                'user_id': user_id,
                'first_name': chat.first_name,
                'username': chat.username,
                'is_premium': is_premium_user(user_id),
                'is_owner': is_owner(user_id),
                'is_admin': is_admin(user_id)
            })
        except:
            users_list.append({
                'user_id': user_id,
                'first_name': 'unknown',
                'username': 'unknown',
                'is_premium': is_premium_user(user_id),
                'is_owner': is_owner(user_id),
                'is_admin': is_admin(user_id)
            })
    return users_list

def is_bot_running(script_owner_id, file_name):
    """check if a bot script is currently running"""
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info:
        # cloud-hosted service: running while DB says so
        if script_info.get('type') == 'cloud':
            row = get_service_for_file(script_owner_id, file_name)
            return bool(row and row[4] == 'running')
        if script_info.get('process'):
            try:
                proc = psutil.Process(script_info['process'].pid)
                return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                return False
    # persistent check for cloud services from DB
    row = get_service_for_file(script_owner_id, file_name)
    if row and row[4] == 'running':
        return True
    return False

def kill_process_tree(process_info):
    """kill a process and all its children"""
    try:
        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            
            try:
                parent.kill()
                parent.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
            
            # close log file if exists
            if process_info.get('log_file'):
                try:
                    process_info['log_file'].close()
                except:
                    pass
                
    except Exception as e:
        logger.error(f"error killing process: {e}")

# --- Automatic Package Installation & Script Running ---
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'tgcrypto': 'tgcrypto',
    'aiohttp': 'aiohttp',
    'aiofiles': 'aiofiles',
    'httpx': 'httpx',
    'motor': 'motor',
    'pymongo': 'pymongo',
    'redis': 'redis',
    'requests': 'requests',
    'bs4': 'beautifulsoup4',
    'pillow': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'flask': 'Flask',
    'django': 'Django',
    'sqlalchemy': 'SQLAlchemy',
    'psutil': 'psutil',
    'yt_dlp': 'yt-dlp',
    'youtube_dl': 'youtube-dl',
    'cryptography': 'cryptography',
    'pytz': 'pytz',
    'pydantic': 'pydantic',
    'apscheduler': 'APScheduler',
    'mutagen': 'mutagen',
    'qrcode': 'qrcode',
    'speedtest': 'speedtest-cli',
    'asyncio': None, 'json': None, 'datetime': None, 'os': None, 'sys': None, 're': None,
    'time': None, 'math': None, 'random': None, 'logging': None, 'threading': None,
    'subprocess': None, 'zipfile': None, 'tempfile': None, 'shutil': None, 'sqlite3': None
}

def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name) 
    if package_name is None: 
        logger.info(f"module '{module_name}' is core. skipping pip install.")
        return False 
    try:
        bot.reply_to(message, f"⚙️ ɪɴsᴛᴀʟʟɪɴɢ `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name, '--timeout', '60', '--retries', '3']
        logger.info(f"running install: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore', timeout=120)
        if result.returncode == 0:
            logger.info(f"installed {package_name}. output:\n{result.stdout}")
            bot.reply_to(message, f"✅ sᴜᴄᴄᴇssғᴜʟʟʏ ɪɴsᴛᴀʟʟᴇᴅ `{package_name}`.", parse_mode='Markdown')
            return True
        else:
            raw = result.stderr or result.stdout or "no output"
            logger.error(f"failed to install {package_name}: {raw[:500]}")
            if len(raw) > 3500:
                raw = raw[:3500] + "\n... (ᴇʀʀᴏʀ ᴛʀᴜɴᴄᴀᴛᴇᴅ)"
            error_msg = f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ɪɴsᴛᴀʟʟ <code>{_esc(package_name)}</code>.\nᴇʀʀᴏʀ:\n<pre>{_esc(raw)}</pre>"
            bot.reply_to(message, error_msg, parse_mode='HTML')
            return False
    except subprocess.TimeoutExpired:
        error_msg = f"❌ ᴛɪᴍᴇᴏᴜᴛ ɪɴsᴛᴀʟʟɪɴɢ `{package_name}`. ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ."
        logger.error(error_msg)
        bot.reply_to(message, error_msg)
        return False
    except Exception as e:
        error_msg = f"❌ ᴇʀʀᴏʀ ɪɴsᴛᴀʟʟɪɴɢ `{package_name}`: {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message, error_msg)
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"📦 ɪɴsᴛᴀʟʟɪɴɢ ɴᴏᴅᴇ ᴘᴀᴄᴋᴀɢᴇ `{module_name}`...", parse_mode='Markdown')
        command = ['npm', 'install', module_name, '--timeout=60000']
        logger.info(f"running npm install: {' '.join(command)} in {user_folder}")
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder, encoding='utf-8', errors='ignore', timeout=120)
        if result.returncode == 0:
            logger.info(f"installed {module_name}. output:\n{result.stdout}")
            bot.reply_to(message, f"✅ sᴜᴄᴄᴇssғᴜʟʟʏ ɪɴsᴛᴀʟʟᴇᴅ ɴᴏᴅᴇ ᴘᴀᴄᴋᴀɢᴇ `{module_name}`.", parse_mode='Markdown')
            return True
        else:
            raw = result.stderr or result.stdout or "no output"
            logger.error(f"failed to install {module_name}: {raw[:500]}")
            if len(raw) > 3500:
                raw = raw[:3500] + "\n... (ᴇʀʀᴏʀ ᴛʀᴜɴᴄᴀᴛᴇᴅ)"
            error_msg = f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ɪɴsᴛᴀʟʟ ɴᴏᴅᴇ ᴘᴀᴄᴋᴀɢᴇ <code>{_esc(module_name)}</code>.\nᴇʀʀᴏʀ:\n<pre>{_esc(raw)}</pre>"
            bot.reply_to(message, error_msg, parse_mode='HTML')
            return False
    except FileNotFoundError:
         error_msg = "❌ ᴇʀʀᴏʀ: 'npm' ɴᴏᴛ ғᴏᴜɴᴅ. ᴇɴsᴜʀᴇ ɴᴏᴅᴇ.js/npm ɪs ɪɴsᴛᴀʟʟᴇᴅ."
         logger.error(error_msg)
         bot.reply_to(message, error_msg)
         return False
    except subprocess.TimeoutExpired:
        error_msg = f"❌ ᴛɪᴍᴇᴏᴜᴛ ɪɴsᴛᴀʟʟɪɴɢ ɴᴏᴅᴇ ᴘᴀᴄᴋᴀɢᴇ `{module_name}`. ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ."
        logger.error(error_msg)
        bot.reply_to(message, error_msg)
        return False
    except Exception as e:
        error_msg = f"❌ ᴇʀʀᴏʀ ɪɴsᴛᴀʟʟɪɴɢ ɴᴏᴅᴇ ᴘᴀᴄᴋᴀɢᴇ `{module_name}`: {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message, error_msg)
        return False

def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    """run python script with automatic dependency installation"""
    max_attempts = 2 
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ʀᴜɴ '{file_name}' ᴀғᴛᴇʀ {max_attempts} ᴀᴛᴛᴇᴍᴘᴛs.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"attempt {attempt} to run python script: {script_path}")

    try:
        if not os.path.exists(script_path):
             bot.reply_to(message_obj_for_reply, f"❌ ᴇʀʀᴏʀ: sᴄʀɪᴘᴛ '{file_name}' ɴᴏᴛ ғᴏᴜɴᴅ!")
             return

        if attempt == 1:
            check_command = [sys.executable, script_path]
            logger.info(f"running python pre-check: {' '.join(check_command)}")
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=10)
                return_code = check_proc.returncode
                logger.info(f"python pre-check. rc: {return_code}. stderr: {stderr[:200]}...")
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("'\"")
                        logger.info(f"detected missing python module: {module_name}")
                        if attempt_install_pip(module_name, message_obj_for_reply):
                            logger.info(f"install ok for {module_name}. retrying run_script...")
                            bot.reply_to(message_obj_for_reply, f"🔧 ɪɴsᴛᴀʟʟ sᴜᴄᴄᴇssғᴜʟ. ʀᴇsᴛᴀʀᴛɪɴɢ '{file_name}'...")
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            bot.reply_to(message_obj_for_reply, f"❌ ɪɴsᴛᴀʟʟ ғᴀɪʟᴇᴅ. ᴄᴀɴɴᴏᴛ ʀᴜɴ '{file_name}'.")
                            return
            except subprocess.TimeoutExpired:
                logger.info("python pre-check timed out, imports likely ok.")
                if check_proc and check_proc.poll() is None: 
                    check_proc.kill()
                    check_proc.communicate()
            except Exception as e:
                 logger.error(f"error in python pre-check: {e}")
                 return

        logger.info(f"starting python process for {script_key}")
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None; process = None
        try: 
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
             logger.error(f"failed to open log file: {e}")
             bot.reply_to(message_obj_for_reply, f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ᴏᴘᴇɴ ʟᴏɢ ғɪʟᴇ: {e}")
             return
        try:
            startupinfo = None; creationflags = 0
            if os.name == 'nt':
                 startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                 startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                [sys.executable, script_path], 
                cwd=user_folder, 
                stdout=log_file, 
                stderr=log_file,
                stdin=subprocess.PIPE, 
                startupinfo=startupinfo, 
                creationflags=creationflags,
                encoding='utf-8', 
                errors='ignore',
                bufsize=1
            )
            logger.info(f"started python process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process, 
                'log_file': log_file, 
                'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 
                'user_folder': user_folder, 
                'type': 'py', 
                'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ ʏᴏᴜʀ sᴄʀɪᴘᴛ '{file_name}' sᴛᴀʀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ! (ᴘɪᴅ: {process.pid})")
        except Exception as e:
            if log_file and not log_file.closed: 
                log_file.close()
            error_msg = f"❌ ᴇʀʀᴏʀ sᴛᴀʀᴛɪɴɢ ʏᴏᴜʀ sᴄʀɪᴘᴛ '{file_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            bot.reply_to(message_obj_for_reply, error_msg)
            if script_key in bot_scripts: 
                del bot_scripts[script_key]
    except Exception as e:
        error_msg = f"❌ ᴜɴᴇxᴘᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ʀᴜɴɴɪɴɢ ʏᴏᴜʀ sᴄʀɪᴘᴛ '{file_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message_obj_for_reply, error_msg)

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    """run js script with automatic dependency installation"""
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ʀᴜɴ '{file_name}' ᴀғᴛᴇʀ {max_attempts} ᴀᴛᴛᴇᴍᴘᴛs.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"attempt {attempt} to run js script: {script_path}")

    try:
        if not os.path.exists(script_path):
             bot.reply_to(message_obj_for_reply, f"❌ ᴇʀʀᴏʀ: sᴄʀɪᴘᴛ '{file_name}' ɴᴏᴛ ғᴏᴜɴᴅ!")
             return

        if attempt == 1:
            check_command = ['node', script_path]
            logger.info(f"running js pre-check: {' '.join(check_command)}")
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=10)
                return_code = check_proc.returncode
                logger.info(f"js pre-check. rc: {return_code}. stderr: {stderr[:200]}...")
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("'\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                             logger.info(f"detected missing node module: {module_name}")
                             if attempt_install_npm(module_name, user_folder, message_obj_for_reply):
                                 logger.info(f"npm install ok for {module_name}. retrying run_js_script...")
                                 bot.reply_to(message_obj_for_reply, f"🔧 ɴᴘᴍ ɪɴsᴛᴀʟʟ sᴜᴄᴄᴇssғᴜʟ. ʀᴇsᴛᴀʀᴛɪɴɢ '{file_name}'...")
                                 time.sleep(2)
                                 threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                                 return
            except subprocess.TimeoutExpired:
                logger.info("js pre-check timed out, imports likely ok.")
                if check_proc and check_proc.poll() is None: 
                    check_proc.kill()
                    check_proc.communicate()
            except Exception as e:
                 logger.error(f"error in js pre-check: {e}")
                 return

        logger.info(f"starting js process for {script_key}")
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None; process = None
        try: 
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"failed to open log file: {e}")
            bot.reply_to(message_obj_for_reply, f"❌ ғᴀɪʟᴇᴅ ᴛᴏ ᴏᴘᴇɴ ʟᴏɢ ғɪʟᴇ: {e}")
            return
        try:
            startupinfo = None; creationflags = 0
            if os.name == 'nt':
                 startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                 startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                ['node', script_path], 
                cwd=user_folder, 
                stdout=log_file, 
                stderr=log_file,
                stdin=subprocess.PIPE, 
                startupinfo=startupinfo, 
                creationflags=creationflags,
                encoding='utf-8', 
                errors='ignore',
                bufsize=1
            )
            logger.info(f"started js process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process, 
                'log_file': log_file, 
                'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 
                'user_folder': user_folder, 
                'type': 'js', 
                'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ ʏᴏᴜʀ ᴊs sᴄʀɪᴘᴛ '{file_name}' sᴛᴀʀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ! (ᴘɪᴅ: {process.pid})")
        except Exception as e:
            if log_file and not log_file.closed: 
                log_file.close()
            error_msg = f"❌ ᴇʀʀᴏʀ sᴛᴀʀᴛɪɴɢ ʏᴏᴜʀ ᴊs sᴄʀɪᴘᴛ '{file_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            bot.reply_to(message_obj_for_reply, error_msg)
            if script_key in bot_scripts: 
                del bot_scripts[script_key]
    except Exception as e:
        error_msg = f"❌ ᴜɴᴇxᴘᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ʀᴜɴɴɪɴɢ ʏᴏᴜʀ ᴊs sᴄʀɪᴘᴛ '{file_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message_obj_for_reply, error_msg)

# ============================================================
#  RAILWAY BACKEND ENGINE  (fully self-contained, hidden)
#  mail.tm -> Magic OTP -> xSolve -> Railway login -> CLI token
# ============================================================

def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_json(obj):
    return _b64url(json.dumps(obj, separators=(",", ":")).encode())


def _gen_ec_keypair():
    """generate a P-256 keypair + public JWK"""
    priv = _ec.generate_private_key(_ec.SECP256R1(), _default_backend())
    nums = priv.public_key().public_numbers()
    jwk = {"kty": "EC", "crv": "P-256",
           "x": _b64url(nums.x.to_bytes(32, "big")),
           "y": _b64url(nums.y.to_bytes(32, "big"))}
    return priv, jwk


def _ec_sign_raw(priv, data):
    """ECDSA P-256/SHA-256 signature as raw r||s (64 bytes)"""
    der = priv.sign(data, _ec.ECDSA(_hashes.SHA256()))
    r, s = _decode_dss(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _magic_headers():
    """build Magic/Toaster request headers (ua-sig + dpop required)"""
    ua_priv, _ = _gen_ec_keypair()
    ua_sig = _b64url(_ec_sign_raw(ua_priv, MAGIC_UA.encode()))
    dp_priv, dp_jwk = _gen_ec_keypair()
    h = _b64url_json({"typ": "dpop+jwt", "alg": "ES256", "jwk": dp_jwk})
    p = _b64url_json({"iat": int(time.time()), "jti": str(uuid.uuid4())})
    dpop = f"{h}.{p}.{_b64url(_ec_sign_raw(dp_priv, f'{h}.{p}'.encode()))}"
    tid = str(uuid.uuid4())
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en_US",
        "content-type": "application/json;charset=UTF-8",
        "dnt": "1", "dpop": dpop,
        "origin": "https://auth.magic.link",
        "referer": "https://auth.magic.link/",
        "sec-ch-ua": '"Brave";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site", "sec-gpc": "1",
        "ua-sig": ua_sig, "user-agent": MAGIC_UA,
        "x-amzn-trace-id": f"Root={tid}",
        "x-magic-api-key": MAGIC_PK, "x-magic-bundle-id": "BundleIDMissing",
        "x-magic-chain": "ETH", "x-magic-meta": "None",
        "x-magic-network": "mainnet", "x-magic-referrer": "https://railway.com",
        "x-magic-sdk": "magic-sdk", "x-magic-trace-id": tid,
    }


def _fridge_headers(fridge):
    tid = str(uuid.uuid4())
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://auth.magic.link",
        "referer": "https://auth.magic.link/",
        "user-agent": MAGIC_UA, "x-amzn-trace-id": f"Root={tid}",
        "x-magic-api-key": MAGIC_PK, "x-magic-chain": "ETH",
        "x-magic-network": "mainnet", "x-magic-referrer": "https://railway.com",
        "x-magic-trace-id": tid, "x-magic-sdk": "magic-sdk",
        "x-magic-bundle-id": "BundleIDMissing",
        "Authorization": f"Bearer {fridge}",
    }


# -------- mail.tm disposable inbox --------
def _mailtm_create_inbox():
    """create a mail.tm inbox, returns (email, password, bearer_token, session)"""
    s = ccr.Session(impersonate="chrome")
    rnd = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    pw = "Stark" + rnd + "Pass"
    doms = s.get("https://api.mail.tm/domains",
                 headers={"accept": "application/ld+json"}, timeout=30).json()
    email = None
    for d in doms.get("hydra:member", []):
        cand = f"st{random.randint(100,999)}{rnd}@{d['domain']}"
        rr = s.post("https://api.mail.tm/accounts",
                    json={"address": cand, "password": pw},
                    headers={"content-type": "application/json",
                             "accept": "application/ld+json"}, timeout=30)
        if rr.status_code in (200, 201):
            email = cand
            break
    if not email:
        raise RuntimeError("mail.tm inbox creation failed")
    tok = s.post("https://api.mail.tm/token",
                 json={"address": email, "password": pw},
                 headers={"content-type": "application/json",
                          "accept": "application/ld+json"}, timeout=30).json()["token"]
    return email, pw, tok, s


def _mailtm_fetch_otp(session, bearer, timeout=120):
    """poll the inbox until a 6-digit Railway OTP appears"""
    auth = {"Authorization": f"Bearer {bearer}", "accept": "application/ld+json"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msgs = session.get("https://api.mail.tm/messages",
                               headers=auth, timeout=30).json().get("hydra:member", [])
            for m in msgs:
                full = session.get(f"https://api.mail.tm/messages/{m['id']}",
                                   headers=auth, timeout=30).json()
                hay = " ".join(str(full.get(k, "")) for k in ("subject", "text", "html", "intro"))
                mm = re.search(r'\b(\d{6})\b', hay)
                if mm:
                    return mm.group(1)
        except Exception:
            pass
        time.sleep(4)
    return None


# -------- smailpro disposable inbox (primary auto-registration source) --------
def _smail_module():
    """lazy import of the vendored smail.py client; wires its solver fallback"""
    import smail as sm
    if not sm.FALLBACK_SOLVER:
        sm.FALLBACK_SOLVER = CAPTCHA_URL
    return sm


def _smail_inbox_channel():
    """create a smailpro mailbox on SMAIL_DOMAIN.
    returns (email, magic_session, fetch_otp_callable)."""
    sm = _smail_module()
    cli = sm.Smail(timeout=45)
    box = cli.create(domain=SMAIL_DOMAIN, username="random",
                     type_="alias", server=1)
    try:
        sm.remember(box)
    except Exception:
        pass
    email = box["address"]
    logger.info(f"[railway] smailpro inbox created: {email}")

    def fetch_otp(timeout=SMAIL_OTP_TIMEOUT):
        return _smail_fetch_otp(sm, cli, box, timeout=timeout)

    return email, ccr.Session(impersonate="chrome"), fetch_otp


def _smail_fetch_otp(sm, cli, box, timeout=SMAIL_OTP_TIMEOUT):
    """poll smailpro inbox until a 6-digit code appears (subject, then body)"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msgs, box = cli.inbox(box)
        except sm.SmailError as e:
            logger.warning(f"[railway] smailpro poll: {e}")
            msgs = []
        if msgs:
            for m in reversed(msgs):
                mm = re.search(r"\b(\d{6})\b", str(m.get("textSubject") or ""))
                if mm:
                    return mm.group(1)
            for m in reversed(msgs):
                try:
                    full = cli.message(box["address"], m["mid"])
                except Exception:
                    continue
                hay = " ".join(str(full.get(k) or "") for k in ("body", "html", "text"))
                hay = sm.strip_html(hay)
                mm = re.search(r"(?<!\d)(\d{6})(?!\d)", hay)
                if mm:
                    return mm.group(1)
        time.sleep(3)
    return None


# -------- Magic OTP + DID token --------
def _magic_otp_start(session, email):
    r = session.post(f"{MAGIC_TOASTER}/v1/auth/email_otp/start",
                     headers=_magic_headers(),
                     json={"email": email, "overrides": {}}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"otp/start failed: {r.status_code} {r.text[:200]}")
    return r.json()["flow_id"]


def _magic_otp_verify(session, flow_id, otp):
    r = session.post(f"{MAGIC_TOASTER}/v1/auth/email_otp/verify",
                     headers=_magic_headers(),
                     json={"challenge_response": otp, "flow_id": flow_id},
                     timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"otp/verify failed: {r.status_code} {r.text[:200]}")
    return r.json()


def _magic_refresh_fridge(session, session_token, current):
    try:
        r = session.get(f"{MAGIC_TOASTER}/v1/auth/access_token",
                        headers={
                            "accept": "application/json, text/plain, */*",
                            "x-magic-api-key": MAGIC_PK,
                            "x-magic-referrer": "https://railway.com",
                            "user-agent": MAGIC_UA,
                            "origin": "https://auth.magic.link",
                            "referer": "https://auth.magic.link/",
                            "Authorization": f"Bearer {session_token}",
                        }, timeout=30)
        if r.status_code == 200:
            return r.json().get("fridge_access_token", current)
    except Exception:
        pass
    return current


def _tee_sign(session, fridge, message_b64):
    tid = str(uuid.uuid4())
    r = session.post(f"{MAGIC_TEE}/v2/wallet/sign/message",
                     headers=_fridge_headers(fridge),
                     json={"message_base64": message_b64, "chain": "ETH",
                           "signing_purpose": "embedded_login"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"tee sign failed: {r.status_code} {r.text[:200]}")
    return r.json()["signature"]


def _build_did_token(session, fridge, wallet, auth_user_id):
    sig1 = _tee_sign(session, fridge, base64.b64encode(b"none").decode())
    now = int(time.time())
    payload = {"iat": now, "ext": now + 900, "iss": f"did:ethr:{wallet}",
               "sub": auth_user_id, "aud": MAGIC_CLIENT_ID, "nbf": now,
               "tid": str(uuid.uuid4()), "add": sig1}
    pj = json.dumps(payload, separators=(",", ":"))
    sig2 = _tee_sign(session, fridge, base64.b64encode(pj.encode()).decode())
    return base64.b64encode(json.dumps([sig2, pj]).encode()).decode()


# -------- Turnstile solver (primary: xsolve, fallback: local solver) --------
def _solve_turnstile():
    errs = []
    try:
        r = requests.post(
            XSOLVE_URL,
            headers={"x-api-key": XSOLVE_KEY, "content-type": "application/json"},
            json={"mode": "turnstile", "url": TURNSTILE_PAGEURL,
                  "sitekey": TURNSTILE_SITEKEY}, timeout=90)
        tok = r.json().get("token")
        if tok:
            logger.info("[captcha] solved via xsolve")
            return tok
        errs.append(f"xsolve {r.status_code} {r.text[:120]}")
    except Exception as e:
        errs.append(f"xsolve {e!r}")

    try:
        r = requests.post(
            CAPTCHA_URL,
            headers={"content-type": "application/json"},
            json={"url": TURNSTILE_PAGEURL,
                  "sitekey": TURNSTILE_SITEKEY}, timeout=90)
        tok = r.json().get("token")
        if tok:
            logger.info("[captcha] solved via fallback solver")
            return tok
        errs.append(f"fallback {r.status_code} {r.text[:120]}")
    except Exception as e:
        errs.append(f"fallback {e!r}")

    raise RuntimeError("captcha solver failed: " + " | ".join(errs))


# -------- Railway login + CLI token --------
def _railway_login_magic(session, did_token):
    hdr = {
        "accept": "*/*", "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json", "dnt": "1",
        "origin": "https://railway.com", "referer": "https://railway.com/",
        "sec-ch-ua": '"Brave";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site", "sec-gpc": "1",
        "user-agent": MAGIC_UA, "Authorization": f"Bearer {did_token}",
    }
    body = {"referralCode": None, "ref": None, "posthogSessionId": str(uuid.uuid4()),
            "turnstileToken": _solve_turnstile(),
            "attribution": {"referringDomain": "$direct", "landingPath": "/dashboard"},
            "signupSurface": "web"}
    r = session.post(f"{RAILWAY_BACKBOARD}/login/magic", headers=hdr, json=body, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"login/magic failed: {r.status_code} {r.text[:200]}")
    return r.json()


def _railway_cli_token(session):
    host = socket.gethostname()
    r = session.get(f"{RAILWAY_BACKBOARD}/login/cli?hostname={host}",
                    headers={"user-agent": MAGIC_UA, "accept": "*/*",
                             "origin": "https://railway.com",
                             "referer": "https://railway.com/"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"login/cli failed: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


def _provision_with_inbox(email, session, fetch_otp, progress=None, password=""):
    """Core auto-registration: mailbox -> Magic OTP -> session -> DID
    -> login/magic -> CLI token -> persist to DB.
    Raises on any failure so the caller can try the next mail channel."""
    if ccr is None or _ec is None:
        raise RuntimeError("missing deps: pip install curl_cffi cryptography")

    def say(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    say("ᴄᴏɴғɪɢᴜʀɪɴɢ ᴇɴᴠɪʀᴏɴᴍᴇɴᴛ...")
    flow = _magic_otp_start(session, email)

    say("ᴠᴇʀɪғʏɪɴɢ sᴇᴛᴜᴘ...")
    otp = fetch_otp()
    if not otp:
        raise RuntimeError("OTP not received in time")
    logger.info(f"[railway] OTP received for {email}")

    say("ɪɴɪᴛɪᴀʟɪᴢɪɴɢ ᴄʟᴏᴜᴅ ʀᴜɴᴛɪᴍᴇ...")
    data = _magic_otp_verify(session, flow, otp)
    session_token = data["session_token"]
    auth_user_id = data["auth_user_id"]
    fridge = data.get("fridge_access_token", "")
    wallet = data["user_data"]["wallets"][0]["public_address"]

    say("ғɪɴᴀʟɪᴢɪɴɢ ᴄʟᴏᴜᴅ ʜᴏsᴛɪɴɢ...")
    fridge = _magic_refresh_fridge(session, session_token, fridge)
    did = _build_did_token(session, fridge, wallet, auth_user_id)
    _railway_login_magic(session, did)
    cli_token = _railway_cli_token(session)

    cookie_json = json.dumps({k: v for k, v in session.cookies.get_dict().items()})

    with RAILWAY_PROVISION_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''insert or replace into railway_accounts
                     (email, password, cli_token, wallet, cookie_json, services_used, max_services, status)
                     values (?, ?, ?, ?, ?, 0, ?, 'active')''',
                  (email, password, cli_token, wallet, cookie_json, RAILWAY_SERVICES_PER_ACCOUNT))
        conn.commit()
        c.execute('select account_id from railway_accounts where email = ?', (email,))
        account_id = c.fetchone()[0]
        conn.close()

    logger.info(f"[railway] account provisioned id={account_id} wallet={wallet}")
    return {"account_id": account_id, "email": email,
            "cli_token": cli_token, "wallet": wallet}


def provision_railway_account(progress=None):
    """
    Fully automate a single Railway account with a mail-channel ladder:
      1) smailpro inbox (captcha: xsolve -> fallback solver)
      2) mail.tm inbox
      -> Magic OTP -> session -> DID -> login/magic -> CLI token -> persist.
    Returns dict(account_id, email, cli_token, wallet).
    `progress` is an optional callable(str) for status updates.
    """
    if ccr is None or _ec is None:
        raise RuntimeError("missing deps: pip install curl_cffi cryptography")

    def say(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    say("ᴘʀᴇᴘᴀʀɪɴɢ ʏᴏᴜʀ ᴄʟᴏᴜᴅ sᴇʀᴠᴇʀ...")

    # channel 1: smailpro (primary)
    try:
        email, ms, fetch_otp = _smail_inbox_channel()
        return _provision_with_inbox(email, ms, fetch_otp, progress=progress)
    except Exception as e:
        logger.warning(f"[railway] smailpro auto-registration failed: {e}; "
                       f"falling back to mail.tm")

    # channel 2: mail.tm (fallback)
    email, pw, bearer, ms = _mailtm_create_inbox()
    logger.info(f"[railway] mail.tm inbox created: {email}")
    fetch = lambda timeout=150: _mailtm_fetch_otp(ms, bearer, timeout)
    return _provision_with_inbox(email, ms, fetch, progress=progress, password=pw)


# ============================================================
#  RAILWAY CLI LAYER  (npm global, multi-account via env token)
# ============================================================

def ensure_railway_cli():
    """ensure `railway` CLI is available; never blocks bot startup"""
    global RAILWAY_BIN
    env = os.environ.copy()
    env["RAILWAY_NO_TELEMETRY"] = "1"
    env["RAILWAY_DISABLE_UPDATE_CHECK"] = "1"
    RAILWAY_BIN = shutil.which("railway")
    if not RAILWAY_BIN:
        logger.info("[railway] CLI not found, installing via npm...")
        try:
            subprocess.run(["npm", "install", "-g", "@railway/cli"],
                           capture_output=True, text=True, timeout=600,
                           stdin=subprocess.DEVNULL, env=env)
            RAILWAY_BIN = shutil.which("railway")
        except FileNotFoundError:
            logger.error("[railway] npm not found; install Node.js on this host")
            return False
        except Exception as e:
            logger.error(f"[railway] CLI install error: {e}")
            return False
    if RAILWAY_BIN:
        logger.info(f"[railway] CLI ready at {RAILWAY_BIN}")
    return bool(RAILWAY_BIN)


def railway_run(args, token, cwd=None, timeout=900, input_text=None):
    """run a railway CLI command as a specific account (via RAILWAY_API_TOKEN)"""
    if not RAILWAY_BIN:
        ensure_railway_cli()
    if not RAILWAY_BIN:
        raise RuntimeError("railway CLI unavailable")
    env = os.environ.copy()
    env["RAILWAY_API_TOKEN"] = token
    env["RAILWAY_NO_TELEMETRY"] = "1"
    env["RAILWAY_DISABLE_UPDATE_CHECK"] = "1"
    p = subprocess.run([RAILWAY_BIN, *args], cwd=cwd or RAILWAY_WORK_DIR, env=env,
                       capture_output=True, text=True, timeout=timeout,
                       input=input_text, encoding="utf-8", errors="ignore")
    return p.returncode, p.stdout, p.stderr


def railway_whoami(token):
    try:
        c, o, e = railway_run(["whoami"], token, timeout=60)
        return (c == 0), (o.strip() or e.strip())
    except Exception as ex:
        return False, str(ex)


# ============================================================
#  ACCOUNT ALLOCATION  (lazy: assign 2 accounts per member)
# ============================================================

def get_user_railway_accounts(user_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''select ra.account_id, ra.email, ra.cli_token, ra.wallet,
                        ra.project_id, ra.project_name, ra.services_used, ra.max_services
                 from railway_accounts ra
                 join user_accounts ua on ua.account_id = ra.account_id
                 where ua.user_id = ? and ra.status = 'active'
                 order by ra.account_id''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def assign_account_to_user(user_id, account_id):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('insert or ignore into user_accounts (user_id, account_id) values (?, ?)',
              (user_id, account_id))
    conn.commit()
    conn.close()


def claim_slot_for_user(user_id, progress=None):
    """
    Return (account_row, needs_project_init) for hosting one file.
    Model: 1 account = 1 project = 1 service (one file).
    Free users have a cap of 1 account; broken accounts are replaced.
    """
    def say(m):
        if progress:
            try: progress(m)
            except Exception: pass

    accounts = get_user_railway_accounts(user_id)
    cap = get_account_cap(user_id)

    # 1) reuse a healthy account with a free service slot
    for acc in list(accounts):
        if acc[6] < acc[7]:
            ok, _ = railway_whoami(acc[2])
            if ok:
                return acc, (acc[4] is None)
            logger.warning(f"Account {acc[0]} token expired, unlinking from user {user_id}")
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("update railway_accounts set status = 'expired' where account_id = ?", (acc[0],))
            c.execute("delete from user_accounts where account_id = ?", (acc[0],))
            conn.commit()
            conn.close()

    # 2) under the cap -> provision a fresh account
    active_count = len(get_user_railway_accounts(user_id))
    if active_count < cap:
        say("Preparing your server...")
        acc_info = provision_railway_account(progress=progress)
        assign_account_to_user(user_id, acc_info["account_id"])
        accounts = get_user_railway_accounts(user_id)
        for acc in accounts:
            if acc[0] == acc_info["account_id"]:
                return acc, True
        raise RuntimeError("account provisioned but not found")

    # 3) cap reached -> friendly limit message (provider never mentioned)
    raise RuntimeError("free plan limit reached")


def init_account_project(user_id, acc_row, service_name, progress=None):
    """create + link a railway project for an account on first use"""
    account_id, email, token, wallet, project_id, project_name, used, mx = acc_row
    workdir = os.path.join(RAILWAY_WORK_DIR, f"acct_{account_id}_{service_name}")
    os.makedirs(workdir, exist_ok=True)
    if project_id:
        railway_run(["link", "-p", project_id], token, cwd=workdir)
        return workdir, project_id
    # create project + link (CLI v4+ removed --workspace on init; project
    # lands in the token's own workspace and --json gives a clean id on v5)
    rc, out, err = railway_run(["init", "--name", f"host{service_name}", "--json"],
                               token, cwd=workdir, input_text="")
    proj_id = None
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                j = json.loads(line)
                if isinstance(j, dict):
                    cand = j.get("id") or (j.get("project") or {}).get("id")
                    if isinstance(cand, str) and len(cand) >= 32:
                        proj_id = cand
                        break
            except Exception:
                pass
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', out + err)
    if m:
        proj_id = m.group(0)
    if not proj_id:
        rc2, out2, err2 = railway_run(["status", "--json"], token, cwd=workdir)
        try:
            proj_id = json.loads(out2).get("id")
        except Exception:
            pass
    if not proj_id:
        # Check if account already has an existing project we can attach to
        try:
            rc_l, out_l, _ = railway_run(["list", "--json"], token, cwd=workdir, timeout=60)
            if rc_l == 0 and out_l.strip():
                projs = json.loads(out_l)
                if isinstance(projs, list) and len(projs) > 0:
                    cand_proj = projs[0].get("id")
                    if cand_proj:
                        proj_id = cand_proj
                        logger.info(f"[railway] Attaching to existing account project {proj_id}")
        except Exception as e_list:
            logger.warning(f"[railway] failed to list projects for account {account_id}: {e_list}")

    if not proj_id:
        clean_lines = [
            line.strip() for line in (err + "\n" + out).splitlines()
            if not line.strip().startswith("warning:")
            and line.strip()
        ]
        err_msg = " | ".join(clean_lines)[:250] or "Failed to initialize cloud project"
        raise RuntimeError(f"Cloud project initialization failed: {err_msg}")
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('update railway_accounts set project_id = ?, project_name = ? where account_id = ?',
              (proj_id, f"host{service_name}", account_id))
    conn.commit()
    conn.close()
    return workdir, proj_id


# ============================================================
#  DEPLOY PACKAGER  (writes Dockerfile/Procfile per upload)
# ============================================================

def _read_requirements_from_py(path):
    mods = set()
    try:
        stdlib = set(sys.stdlib_module_names) | {"__future__", "site"}
        src = open(path, "r", encoding="utf-8", errors="ignore").read()
        for m in re.findall(r'(?:from|import)\s+([a-zA-Z0-9_]+)', src):
            low = m.lower()
            pkg = TELEGRAM_MODULES.get(low, m)
            if not pkg:
                continue
            if pkg.lower() == low and pkg in stdlib:
                continue
            mods.add(pkg)
    except Exception:
        pass
    return mods


def _scan_all_py_requirements(dir_path):
    """recursively scan all python files in dir_path for external pip requirements"""
    mods = set()
    stdlib = set(sys.stdlib_module_names) | {"__future__", "site"}
    local_names = set()
    try:
        for item in os.listdir(dir_path):
            local_names.add(item.lower())
            if item.endswith('.py'):
                local_names.add(item[:-3].lower())
    except Exception:
        pass

    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'venv', '.venv', 'env', 'node_modules')]
        for f in files:
            if f.endswith('.py'):
                fp = os.path.join(root, f)
                try:
                    src = open(fp, "r", encoding="utf-8", errors="ignore").read()
                    for m in re.findall(r'(?:from|import)\s+([a-zA-Z0-9_]+)', src):
                        low = m.lower()
                        if low in local_names:
                            continue
                        pkg = TELEGRAM_MODULES.get(low, m)
                        if not pkg:
                            continue
                        if pkg.lower() == low and pkg in stdlib:
                            continue
                        mods.add(pkg)
                except Exception:
                    pass
    return mods


def safe_extract_zip(zip_path, target_dir):
    """safely extracts a zip into target_dir; flattens single root dir if present"""
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as z:
        valid_members = [
            m for m in z.infolist()
            if not m.is_dir()
            and not m.filename.startswith('__MACOSX/')
            and not os.path.basename(m.filename).startswith('._')
        ]
        first_dirs = [m.filename.split('/')[0] for m in valid_members if '/' in m.filename]
        common_root = first_dirs[0] if (first_dirs and all(m.filename.startswith(first_dirs[0] + '/') for m in valid_members)) else None

        for m in valid_members:
            rel = m.filename[len(common_root) + 1:] if common_root and m.filename.startswith(common_root + '/') else m.filename
            norm_rel = os.path.normpath(rel)
            if norm_rel.startswith('..') or os.path.isabs(norm_rel):
                continue
            out_path = os.path.join(target_dir, norm_rel)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with z.open(m) as src, open(out_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)


def inspect_zip_runnables(zip_path):
    """returns a sorted list of relative runnable file paths inside the zip"""
    candidates = []
    if not os.path.exists(zip_path):
        return candidates
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            valid_members = [
                m for m in z.infolist()
                if not m.is_dir()
                and not m.filename.startswith('__MACOSX/')
                and not os.path.basename(m.filename).startswith('._')
            ]
            first_dirs = [m.filename.split('/')[0] for m in valid_members if '/' in m.filename]
            common_root = first_dirs[0] if (first_dirs and all(m.filename.startswith(first_dirs[0] + '/') for m in valid_members)) else None

            for m in valid_members:
                rel = m.filename[len(common_root) + 1:] if common_root and m.filename.startswith(common_root + '/') else m.filename
                rel = rel.replace('\\', '/')
                ext = os.path.splitext(rel)[1].lower()
                if ext in ('.py', '.js', '.ts', '.sh'):
                    if any(x in rel for x in ('__pycache__', 'node_modules', '.venv', 'site-packages')):
                        continue
                    candidates.append(rel)
    except Exception as e:
        logger.error(f"error inspecting zip {zip_path}: {e}")

    def score(p):
        fn = os.path.basename(p).lower()
        s = 0
        if fn in ('bot.py', 'bot.js', 'bot.ts'): s += 100
        elif fn in ('main.py', 'main.js', 'main.ts'): s += 95
        elif fn in ('app.py', 'app.js', 'app.ts'): s += 90
        elif fn in ('run.py', 'start.py'): s += 85
        elif fn in ('server.py', 'server.js'): s += 80
        elif fn in ('index.py', 'index.js'): s += 75
        elif fn.endswith('.py'): s += 50
        elif fn.endswith(('.js', '.ts')): s += 40
        s -= p.count('/') * 10
        return s

    candidates.sort(key=score, reverse=True)
    return candidates


def package_for_railway(user_id, file_path, file_name, workdir):
    """write a runnable container wrapper around the user's upload"""
    os.makedirs(workdir, exist_ok=True)
    ext = os.path.splitext(file_name)[1].lower()

    if ext == ".zip":
        # clean previous files preserving railway cli state
        for item in os.listdir(workdir):
            if item in ('.railway', 'railway.json'):
                continue
            item_path = os.path.join(workdir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
            except Exception:
                pass

        safe_extract_zip(file_path, workdir)

        # entrypoint determination
        entrypoint = get_zip_entrypoint(user_id, file_name)
        candidates = inspect_zip_runnables(file_path)
        if not entrypoint or not os.path.exists(os.path.join(workdir, entrypoint)):
            entrypoint = candidates[0] if candidates else "bot.py"
            set_zip_entrypoint(user_id, file_name, entrypoint)

        entry_ext = os.path.splitext(entrypoint)[1].lower()
        if entry_ext == ".py":
            detected_reqs = _scan_all_py_requirements(workdir)
            req_file = os.path.join(workdir, "requirements.txt")
            existing_reqs = set()
            if os.path.exists(req_file):
                try:
                    for line in open(req_file, "r", encoding="utf-8", errors="ignore"):
                        line = line.strip()
                        if line and not line.startswith("#"):
                            existing_reqs.add(line)
                except Exception:
                    pass
            all_reqs = sorted(existing_reqs | detected_reqs)
            with open(req_file, "w", encoding="utf-8") as f:
                f.write("\n".join(all_reqs) + "\n")

            dockerfile = (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "ENV PYTHONUNBUFFERED=1\n"
                "ENV PYTHONDONTWRITEBYTECODE=1\n"
                "ENV PIP_NO_CACHE_DIR=1\n"
                "ENV PIP_DISABLE_PIP_VERSION_CHECK=1\n"
                "ENV DEBIAN_FRONTEND=noninteractive\n"
                "ENV PYTHONPATH=/app\n"
                "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
                "    build-essential gcc git ffmpeg libffi-dev libssl-dev ca-certificates curl \\\n"
                "    && rm -rf /var/lib/apt/lists/*\n"
                "COPY . /app\n"
                "RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \\\n"
                "    (if [ -f requirements.txt ]; then \\\n"
                "        pip install --no-cache-dir -r requirements.txt || \\\n"
                "        (while IFS= read -r pkg || [ -n \"$pkg\" ]; do \\\n"
                "            case \"$pkg\" in ''|'#'*) continue;; esac; \\\n"
                "            pip install --no-cache-dir \"$pkg\" || echo \"skipped $pkg\"; \\\n"
                "         done < requirements.txt); \\\n"
                "    fi)\n"
                f'CMD ["python", "{entrypoint}"]\n'
            )
        elif entry_ext in (".js", ".ts"):
            dockerfile = (
                "FROM node:20-slim\n"
                "WORKDIR /app\n"
                "ENV NODE_ENV=production\n"
                "RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*\n"
                "COPY . /app\n"
                "RUN if [ -f package.json ]; then npm install --production || npm install; fi\n"
                f'CMD ["node", "{entrypoint}"]\n'
            )
        elif entry_ext == ".sh":
            dockerfile = (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "RUN apt-get update && apt-get install -y --no-install-recommends bash curl git ca-certificates && rm -rf /var/lib/apt/lists/*\n"
                "COPY . /app\n"
                f"RUN chmod +x {entrypoint}\n"
                f'CMD ["bash", "{entrypoint}"]\n'
            )
        else:
            dockerfile = (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "COPY . /app\n"
                f'CMD ["python", "{entrypoint}"]\n'
            )
        with open(os.path.join(workdir, "Dockerfile"), "w", encoding="utf-8") as f:
            f.write(dockerfile)
        return workdir

    # Single-file packaging
    dest = os.path.join(workdir, f"main{ext}")
    shutil.copy2(file_path, dest)

    if ext == ".py":
        reqs = _read_requirements_from_py(dest)
        with open(os.path.join(workdir, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(reqs)) + "\n")
        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "ENV PYTHONUNBUFFERED=1\n"
            "ENV PIP_NO_CACHE_DIR=1\n"
            "ENV PYTHONPATH=/app\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends \\\n"
            "    build-essential gcc git ffmpeg libffi-dev libssl-dev ca-certificates curl \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
            "COPY . /app\n"
            "RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \\\n"
            "    (if [ -f requirements.txt ]; then \\\n"
            "        pip install --no-cache-dir -r requirements.txt || \\\n"
            "        (while IFS= read -r pkg || [ -n \"$pkg\" ]; do \\\n"
            "            case \"$pkg\" in ''|'#'*) continue;; esac; \\\n"
            "            pip install --no-cache-dir \"$pkg\" || echo \"skipped $pkg\"; \\\n"
            "         done < requirements.txt); \\\n"
            "    fi)\n"
            f'CMD ["python", "main{ext}"]\n'
        )
    elif ext in (".js", ".ts"):
        dockerfile = (
            "FROM node:20-slim\n"
            "WORKDIR /app\n"
            "ENV NODE_ENV=production\n"
            "COPY . /app\n"
            "RUN npm install || true\n"
            f'CMD ["node", "main{ext}"]\n'
        )
    elif ext in (".html", ".htm", ".css"):
        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY . /app\n"
            'CMD ["python", "-m", "http.server", "8080"]\n'
        )
    else:
        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY . /app\n"
            f'CMD ["python", "-c", "print(\'hosted\')"]\n'
        )
    with open(os.path.join(workdir, "Dockerfile"), "w", encoding="utf-8") as f:
        f.write(dockerfile)
    return workdir


def ensure_railway_service(workdir, token, service_name):
    """make sure a service with this name exists on the linked project;
    used before `up --service`, which bails on non-existent services"""
    try:
        rc, _, _ = railway_run(["service", service_name], token, cwd=workdir, timeout=120)
        if rc == 0:
            return True
    except Exception:
        pass
    rc, out, err = railway_run(["add", "--service", service_name], token,
                               cwd=workdir, timeout=300, input_text="")
    if rc != 0:
        logger.warning(f"[railway] service creation for {service_name}: "
                       f"{(err.strip() or out.strip())[:200]}")
    return rc == 0


def deploy_to_railway(user_id, acc_row, file_path, file_name, progress=None):
    """Package + deploy a user's file to the account's railway project."""
    def say(m):
        if progress:
            try: progress(m)
            except Exception: pass

    account_id, email, token, wallet, project_id, project_name, used, mx = acc_row
    slug = re.sub(r'[^a-zA-Z0-9]', '', os.path.splitext(file_name)[0])[:24].lower() or "app"
    service_name = f"{user_id}-{slug}"

    say("Preparing your app...")
    workdir, proj_id = init_account_project(user_id, acc_row, service_name, progress)
    package_for_railway(user_id, file_path, file_name, workdir)

    say("Deploying container to cloud...")
    ensure_railway_service(workdir, token, service_name)
    up_args = ["up", "--detach", "--service", service_name]
    rc, out, err = railway_run(up_args, token, cwd=workdir)

    svc_id = hashlib.md5(f"{account_id}_{service_name}".encode()).hexdigest()[:16]
    url = None

    # record service; only count a slot if this is a brand-new deployment
    existing = get_service_for_file(user_id, file_name)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    if not existing:
        c.execute('update railway_accounts set services_used = services_used + 1 where account_id = ?',
                  (account_id,))
    c.execute('''insert or replace into railway_services
                 (service_id, user_id, account_id, file_name, project_id, service_name, url, status)
                 values (?, ?, ?, ?, ?, ?, ?, 'running')''',
              (svc_id, user_id, account_id, file_name, proj_id, service_name, url))
    conn.commit()
    conn.close()

    if rc != 0:
        raise RuntimeError(f"deploy failed: {err[:300] or out[:300]}")
    return {"service_id": svc_id, "service_name": service_name, "url": url,
            "workdir": workdir, "account_id": account_id}


def get_service_for_file(user_id, file_name):
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('''select service_id, account_id, service_name, url, status, project_id
                 from railway_services where user_id = ? and file_name = ?
                 order by created_date desc limit 1''', (user_id, file_name))
    row = c.fetchone()
    conn.close()
    return row


def _ensure_linked(workdir, token, project_id):
    """Make sure the workdir has a linked Railway project so CLI commands work."""
    cfg_dir = os.path.join(workdir, ".railway")
    cfg_file = os.path.join(cfg_dir, "config.json")
    if project_id and not os.path.isfile(cfg_file):
        os.makedirs(cfg_dir, exist_ok=True)
        railway_run(["link", "-p", project_id], token, cwd=workdir, timeout=60)
    elif not os.path.isfile(cfg_file):
        # no project_id and no config — try linking via status
        railway_run(["link"], token, cwd=workdir, timeout=60, input_text="\n")


def stop_service(user_id, file_name):
    row = get_service_for_file(user_id, file_name)
    if not row:
        return False, "not found"
    svc_id, account_id, service_name, url, status, project_id = row
    accounts = get_user_railway_accounts(user_id)
    token = None
    for acc in accounts:
        if acc[0] == account_id:
            token = acc[2]; break
    if not token:
        return False, "account missing"
    workdir = os.path.join(RAILWAY_WORK_DIR, f"acct_{account_id}_{service_name}")
    os.makedirs(workdir, exist_ok=True)
    try:
        _ensure_linked(workdir, token, project_id)
        rc, out, err = railway_run(["down", "--service", service_name, "--yes"], token, cwd=workdir)
        if rc != 0:
            logger.warning(f"[stop] railway down failed for {service_name}: {(err or out)[:200]}")
    except Exception as e:
        logger.warning(f"[stop] railway down exception for {service_name}: {e}")
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("update railway_services set status='stopped' where service_id=?", (svc_id,))
    conn.commit()
    conn.close()
    return True, "stopped"


def delete_service(user_id, file_name):
    row = get_service_for_file(user_id, file_name)
    if not row:
        return
    svc_id, account_id, service_name, url, status, project_id = row
    stop_service(user_id, file_name)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute('delete from railway_services where service_id = ?', (svc_id,))
    # free a slot on the account
    c.execute('update railway_accounts set services_used = max(0, services_used - 1) where account_id = ?',
              (account_id,))
    conn.commit()
    conn.close()


def service_logs(user_id, file_name, lines=100, log_type="deploy"):
    """Fetch logs from Railway for a deployed service.
    log_type: 'deploy' (default runtime logs), 'build' (build/compile logs)
    """
    row = get_service_for_file(user_id, file_name)
    if not row:
        return None
    svc_id, account_id, service_name, url, status, project_id = row
    accounts = get_user_railway_accounts(user_id)
    token = None
    for acc in accounts:
        if acc[0] == account_id:
            token = acc[2]; break
    if not token:
        return None
    workdir = os.path.join(RAILWAY_WORK_DIR, f"acct_{account_id}_{service_name}")
    os.makedirs(workdir, exist_ok=True)
    try:
        _ensure_linked(workdir, token, project_id)
        log_args = ["logs", "--service", service_name, "--lines", str(lines)]
        if log_type == "build":
            log_args.append("--build")
        rc, out, err = railway_run(log_args, token, cwd=workdir, timeout=120)
        result = (out or err or "no output").strip()
        return result[:4000] if result else "no output"
    except Exception as e:
        return f"error fetching logs: {e}"


# --- Database Operations ---
DB_LOCK = threading.Lock()

def save_user(user_id, username, first_name, last_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('insert or replace into users (user_id, username, first_name, last_name) values (?, ?, ?, ?)',
                      (user_id, username, first_name, last_name))
            conn.commit()
        except Exception as e:
            logger.error(f"error saving user: {e}")
        finally:
            conn.close()

def save_user_file(user_id, file_name, file_type='unknown', file_path=''):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('insert or replace into user_files (user_id, file_name, file_type, file_path) values (?, ?, ?, ?)',
                      (user_id, file_name, file_type, file_path))
            conn.commit()
            if user_id not in user_files:
                user_files[user_id] = []
            # remove existing file with same name
            user_files[user_id] = [(fn, ft, fp) for fn, ft, fp in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type, file_path))
        except Exception as e:
            logger.error(f"error saving file: {e}")
        finally:
            conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('delete from user_files where user_id = ? and file_name = ?', (user_id, file_name))
            c.execute('delete from zip_configs where user_id = ? and file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
        except Exception as e:
            logger.error(f"error removing file: {e}")
        finally:
            conn.close()

def get_zip_entrypoint(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('select entrypoint from zip_configs where user_id = ? and file_name = ?',
                      (user_id, file_name))
            row = c.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"error getting zip entrypoint: {e}")
            return None
        finally:
            conn.close()

def set_zip_entrypoint(user_id, file_name, entrypoint):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('insert or replace into zip_configs (user_id, file_name, entrypoint) values (?, ?, ?)',
                      (user_id, file_name, entrypoint))
            conn.commit()
        except Exception as e:
            logger.error(f"error setting zip entrypoint: {e}")
        finally:
            conn.close()

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('insert or ignore into active_users (user_id) values (?)', (user_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"error adding active user: {e}")
        finally:
            conn.close()

def save_subscription(user_id, expiry, plan_type='unlimited', file_limit=999):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('insert or replace into subscriptions (user_id, expiry, plan_type, file_limit) values (?, ?, ?, ?)',
                      (user_id, expiry_str, plan_type, file_limit))
            conn.commit()
            user_subscriptions[user_id] = {
                'expiry': expiry,
                'plan_type': plan_type,
                'file_limit': file_limit
            }
        except Exception as e:
            logger.error(f"error saving subscription: {e}")
        finally:
            conn.close()

# --- Menu Creation ---
def create_main_menu_keyboard(user_id):
    """create main menu keyboard with buttons"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

    markup.row('📤 Upload', '📁 My Files')
    markup.row('💎 Premium', '📊 Status')
    markup.row('📞 Support')

    if is_admin(user_id):
        markup.row('👑 Admin Panel')
        markup.row('📢 Broadcast', '🖥️ Running Code')
        lock_label = '🔓 Unlock Bot' if bot_locked else '🔒 Lock Bot'
        markup.row(lock_label)

    if is_owner(user_id):
        markup.row('⚙️ Settings', '📊 Bot Stats')

    return markup


def get_running_script_count():
    count = 0
    for key, script_info in list(bot_scripts.items()):
        try:
            if script_info['process'].poll() is None:
                count += 1
        except Exception:
            pass
    return count


def handle_admin_panel_text(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, '❌ Admin access required!')
        return

    total_users = len(active_users)
    total_files = sum(len(v) for v in user_files.values())
    running_scripts = get_running_script_count()
    bot_status = '🔒 Locked' if bot_locked else '🔓 Unlocked'

    owner_cmds = ''
    if is_owner(user_id):
        owner_cmds = (
            '• /addadmin <user_id> - Add admin\n'
            '• /removeadmin <user_id> - Remove admin\n'
        )

    text = (
        '👑 *Admin Panel*\n\n'
        '📊 *System Status:*\n'
        f'• Active Users: {total_users}\n'
        f'• Total Files: {total_files}\n'
        f'• Running Scripts: {running_scripts}\n'
        f'• Bot Status: {bot_status}\n\n'
        '🛠️ *Available Commands:*\n'
        '• /addsub <user_id> <days> - Add subscription\n'
        '• /removesub <user_id> - Remove subscription\n'
        '• /broadcast - Send broadcast message\n'
        + owner_cmds +
        '\n📈 Use the admin buttons for quick actions!'
    )
    markup = create_admin_panel_keyboard(user_id)
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')


def build_main_menu_text(user_id, first_name="there"):
    file_limit = get_user_file_limit(user_id)
    limit_str = "∞" if file_limit == float('inf') else str(file_limit)
    text = (
        f"{pe('rocket', '🚀')} <b>Cloud Hosting Services</b>\n"
        f"{DIVIDER}\n"
        f"👋 Welcome, <b>{_esc(first_name or 'there')}</b>!\n\n"
        f"⚡ <b>Fast & Reliable 24/7 Cloud Bot Hosting</b>\n"
        f"📦 Host Python, Node.js, and ZIP projects easily.\n\n"
        f"👤 <b>Plan:</b> {get_user_status(user_id)}\n"
        f"📁 <b>Hosted Projects:</b> <code>{get_user_file_count(user_id)}/{limit_str}</code>\n"
        f"🆓 <b>Free Tier:</b> {FREE_USER_LIMIT} Project (Online 24/7)\n"
        f"💎 <b>Premium:</b> $2 (10 Bots) • $7 (Unlimited)\n"
        f"{DIVIDER}\n"
        f"📢 <a href=\"{CHANNEL_URL}\">Updates Channel</a>  •  🛟 {SUPPORT_LINE}"
    )
    return text


def send_main_menu(chat_id, user_id, first_name="there"):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📢 Updates Channel", url=CHANNEL_URL))
    try:
        bot.send_message(chat_id, build_main_menu_text(user_id, first_name),
                         reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(chat_id, build_main_menu_text(user_id, first_name))
    bot.send_message(chat_id, "👇 Choose an option below:",
                     reply_markup=create_main_menu_keyboard(user_id))


def create_start_hosting_keyboard():
    """create keyboard with start hosting button (for after file upload)"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('🚀 sᴛᴀʀᴛ ʜᴏsᴛɪɴɢ', callback_data='start_hosting'))
    return markup

def create_manage_files_keyboard(user_id):
    """create inline keyboard for managing files"""
    user_files_list = user_files.get(user_id, [])
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if not user_files_list:
        markup.add(types.InlineKeyboardButton("📭 No files yet", callback_data='no_files'))
    else:
        for file_name, file_type, file_path in user_files_list:
            is_running = is_bot_running(user_id, file_name)
            status_emoji = "🟢" if is_running else "🔴"
            fkey = get_file_key(file_name)
            extra = ""
            if file_name.lower().endswith('.zip'):
                ent = get_zip_entrypoint(user_id, file_name)
                if ent:
                    extra = f" [{ent}]"
            button_text = f"{status_emoji} {file_name}{extra}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=f'file_{user_id}_{fkey}'))
    
    markup.add(types.InlineKeyboardButton("🔙 Main Menu", callback_data='back_to_main'))
    return markup

def create_file_management_buttons(user_id, file_name, is_running=True):
    markup = types.InlineKeyboardMarkup(row_width=2)
    fkey = get_file_key(file_name)
    if is_running:
        markup.row(
            types.InlineKeyboardButton("⏹️ Stop", callback_data=f'stop_{user_id}_{fkey}'),
            types.InlineKeyboardButton("🔄 Restart", callback_data=f'restart_{user_id}_{fkey}')
        )
    else:
        markup.row(
            types.InlineKeyboardButton("🚀 Start", callback_data=f'start_{user_id}_{fkey}'),
        )
    markup.row(
        types.InlineKeyboardButton("📋 Logs", callback_data=f'logs_{user_id}_{fkey}'),
        types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{user_id}_{fkey}')
    )
    if file_name.lower().endswith('.zip'):
        markup.row(
            types.InlineKeyboardButton("🎯 Run File", callback_data=f'ent_{user_id}_{fkey}'),
            types.InlineKeyboardButton("📦 Update Zip", callback_data=f'upd_{user_id}_{fkey}')
        )
    else:
        markup.row(
            types.InlineKeyboardButton("📦 Update / Replace", callback_data=f'upd_{user_id}_{fkey}')
        )
    markup.row(
        types.InlineKeyboardButton("🔙 Back to Files", callback_data='manage_files'),
        types.InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main')
    )
    return markup

def create_entrypoint_selection_keyboard(user_id, file_name, candidates, selected_entry):
    markup = types.InlineKeyboardMarkup(row_width=1)
    fkey = get_file_key(file_name)
    for idx, cand in enumerate(candidates[:6]):
        mark = " ✅" if cand == selected_entry else ""
        icon = "🐍" if cand.endswith(".py") else "📄"
        btn_text = f"{icon} {cand}{mark}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"set_{user_id}_{fkey}_{idx}"))
    markup.add(types.InlineKeyboardButton("✏️ Custom Run File", callback_data=f"cst_{user_id}_{fkey}"))
    is_running = is_bot_running(user_id, file_name)
    if is_running:
        markup.add(types.InlineKeyboardButton("🔄 Apply & Redeploy Now", callback_data=f"rdp_{user_id}_{fkey}"))
    else:
        markup.add(types.InlineKeyboardButton("🚀 Start Hosting", callback_data=f"start_{user_id}_{fkey}"))
    markup.row(
        types.InlineKeyboardButton("🔙 Back to File", callback_data=f"file_{user_id}_{fkey}"),
        types.InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main')
    )
    return markup

def create_admin_panel_keyboard(user_id=None):
    """create admin panel keyboard - owner-only buttons hidden from plain admins"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        '📊 ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs',
        '👥 ᴀʟʟ ᴜsᴇʀs',
        '🎯 ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs',
        '📢 ʙʀᴏᴀᴅᴄᴀsᴛ',
    ]
    # admin & owner buttons
    if user_id is None or is_admin(user_id):
        buttons += [
            '🔑 ɢᴇɴᴇʀᴀᴛᴇ ᴋᴇʏ',
            '🗑️ ᴅᴇʟᴇᴛᴇ ᴋᴇʏ',
            '🔢 ᴛᴏᴛᴀʟ ᴋᴇʏs',
        ]
    if user_id is None or is_owner(user_id):
        buttons += [
            '📈 ғɪʟᴇ ʟɪᴍɪᴛ',
            '⚙️ ʙᴏᴛ sᴇᴛᴛɪɴɢs',
        ]
    buttons.append('🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ')

    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i+1])
        else:
            markup.row(buttons[i])

    return markup

# --- Command Handlers ---
@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message):
    user_id = message.from_user.id
    ensure_admin_status(user_id, message.from_user.username)
    
    # check if bot is locked
    if bot_locked and not is_admin(user_id):
        bot.send_message(message.chat.id, 
                        to_small_caps("""
🔒 *ʙᴏᴛ ɪs ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ*

❗ ᴛʜɪs ʙᴏᴛ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ.
📅 ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.

👑 *sᴜᴘᴘᴏʀᴛ:* {SUPPORT_LINE}
📞 ғᴏʀ ᴀɴʏ ᴜʀɢᴇɴᴛ ǫᴜᴇʀɪᴇs ᴏʀ sᴜᴘᴘᴏʀᴛ
                        """),
                        parse_mode='Markdown')
        return
    
    # Check force join for non-admin users
    if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
        force_message = create_force_join_message()
        force_markup = create_force_join_keyboard()
        bot.send_message(message.chat.id, force_message, reply_markup=force_markup, parse_mode='Markdown')
        return
    
    # user is verified or admin, show main menu
    add_active_user(user_id)
    save_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    send_main_menu(message.chat.id, user_id, message.from_user.first_name)


def handle_bot_speed_text(message):
    import time
    start = time.time()
    msg = bot.send_message(message.chat.id, '⚡ Pinging...')
    elapsed = round((time.time() - start) * 1000)
    bot.edit_message_text(
        f'⚡ *Bot Speed*\n\n🏓 Ping: `{elapsed}ms`\n✅ Bot is Online and Running!',
        message.chat.id, msg.message_id, parse_mode='Markdown'
    )


def handle_contact_owner_text(message):
    text = (
        f"📞 <b>Support</b>\n"
        f"{DIVIDER}\n"
        f"📢 Channel: {CHANNEL_USERNAME}\n"
        f"👤 Admins: {SUPPORT_LINE}\n"
        f"{DIVIDER}\n"
        f"<i>Need help with hosting or premium? Message an admin.</i>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📢 Join Channel', url=CHANNEL_URL))
    for uname in SUPPORT_USERS:
        markup.add(types.InlineKeyboardButton(f'👤 {uname}', url=f'https://t.me/{uname.lstrip("@")}'))
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')


def handle_subscriptions_text(message):
    handle_buy_subscription_text(message)


def handle_running_all_code_text(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, '❌ Admin access required!')
        return
    
    running = []
    for key, script_info in list(bot_scripts.items()):
        try:
            if script_info['process'].poll() is None:  # still running
                parts = str(key).split('_', 1)
                uid = parts[0] if len(parts) >= 1 else '?'
                fname = parts[1] if len(parts) >= 2 else str(key)
                pid = script_info['process'].pid
                start_time = script_info.get('start_time', datetime.now())
                running.append((uid, fname, pid, start_time))
        except Exception:
            pass
    
    if not running:
        bot.send_message(message.chat.id, '🟢 *Running Code Monitor*\n\n📊 Active Scripts: 0\n\nNo scripts currently running.', parse_mode='Markdown')
        return
    
    text = f'🟢 *Running Code Monitor*\n\n📊 Active Scripts: {len(running)}\n\n'
    for uid, fname, pid, start_time in running:
        ext = os.path.splitext(fname)[1].lower()
        lang = SUPPORTED_EXTENSIONS.get(ext, 'Unknown').capitalize()
        emoji = '🐍' if ext == '.py' else '📄'
        started = start_time.strftime('%H:%M:%S')
        text += f'{emoji} *{fname}* ({lang})\n👤 User: `{uid}`\n🆔 PID: `{pid}`\n🕐 Started: `{started}`\n\n'
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')


def handle_lock_unlock_bot_text(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, '❌ Admin access required!')
        return
    update_bot_locked_status(not bot_locked)
    state = '🔒 Locked' if bot_locked else '🔓 Unlocked'
    bot.send_message(message.chat.id, f'✅ Bot is now *{state}*', parse_mode='Markdown')
    # refresh keyboard so lock/unlock label updates
    markup = create_main_menu_keyboard(message.from_user.id)
    bot.send_message(message.chat.id, '🔄 Menu updated.', reply_markup=markup)


# --- Text Message Handlers ---
@bot.message_handler(func=lambda message: True)
def handle_text_messages(message):
    user_id = message.from_user.id
    ensure_admin_status(user_id, message.from_user.username)
    
    # check if bot is locked for non-admin users
    if bot_locked and not is_admin(user_id):
        bot.send_message(message.chat.id, 
                        to_small_caps("""
🔒 *ʙᴏᴛ ɪs ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ*

❗ ᴛʜɪs ʙᴏᴛ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ.
📅 ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.

👑 *sᴜᴘᴘᴏʀᴛ:* {SUPPORT_LINE}
📞 ғᴏʀ ᴀɴʏ ᴜʀɢᴇɴᴛ ǫᴜᴇʀɪᴇs ᴏʀ sᴜᴘᴘᴏʀᴛ
                        """),
                        parse_mode='Markdown')
        return
    
    # Check force join for non-admin users
    if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
        force_message = create_force_join_message()
        force_markup = create_force_join_keyboard()
        bot.send_message(message.chat.id, force_message, reply_markup=force_markup, parse_mode='Markdown')
        return
    
    text = message.text or ''

    # Handle /cancel command or text
    if text.strip() in ('/cancel', 'cancel', '❌ Cancel'):
        if user_id in pending_zip_updates:
            target_name = pending_zip_updates.pop(user_id)
            bot.reply_to(message, f"❌ Update for <code>{_esc(target_name)}</code> cancelled.", parse_mode='HTML')
            return
        bot.reply_to(message, "❌ Operation cancelled.")
        return

    # Handle direct commands
    if text.startswith('/url ') or text.strip() == '/url':
        handle_url_command(message)
        return
    
    if text == '📤 Upload' or text == '📤 Upload File':
        handle_upload_file_text(message)
    elif text == '📁 My Files' or text == '📁 Check Files':
        handle_manage_files_text(message)
    elif text == '⚡ Bot Speed':
        handle_bot_speed_text(message)
    elif text in ('📊 Status', '📊 Statistics'):
        handle_status_text(message)
    elif text == '💎 Premium' or text == '💳 Subscriptions':
        handle_subscriptions_text(message)
    elif text == '📞 Support' or text == '📞 Contact Owner':
        handle_contact_owner_text(message)
    # --- Admin actions (admin + owner) ---
    elif text == '👑 Admin Panel' and is_admin(user_id):
        handle_admin_panel_text(message)
    elif text == '📢 Broadcast' and is_admin(user_id):
        handle_broadcast_text(message)
    elif text in ('🖥️ Running Code', '🟢 Running All Code') and is_admin(user_id):
        handle_running_all_code_text(message)
    elif text in ('🔒 Lock Bot', '🔓 Unlock Bot') and is_admin(user_id):
        handle_lock_unlock_bot_text(message)
    # --- Owner-only actions ---
    elif text in ('⚙️ Settings', '⚙️ Bot Settings') and is_owner(user_id):
        handle_bot_settings_text(message)
    elif text in ('📊 Bot Stats', '📊 Bot Statistics') and is_owner(user_id):
        handle_bot_statistics_text(message)
    # legacy small-caps button fallbacks (admin panel submenus)
    elif text == '📢 ʙʀᴏᴀᴅᴄᴀsᴛ' and is_admin(user_id):
        handle_broadcast_text(message)
    elif text == '👥 ᴀʟʟ ᴜsᴇʀs' and is_admin(user_id):
        handle_all_users_text(message)
    elif text == '🎯 ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs' and is_admin(user_id):
        handle_premium_users_text(message)
    elif text == '📊 ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs' and is_admin(user_id):
        handle_bot_statistics_text(message)
    elif text == '⚙️ ʙᴏᴛ sᴇᴛᴛɪɴɢs' and is_owner(user_id):
        handle_bot_settings_text(message)
    elif text in ('🔑 ɢᴇɴᴇʀᴀᴛᴇ ᴋᴇʏ', '🔑 Generate Key', '/genkey') and is_admin(user_id):
        handle_generate_key_text(message)
    elif text == '🗑️ ᴅᴇʟᴇᴛᴇ ᴋᴇʏ' and is_owner(user_id):
        handle_delete_key_text(message)
    elif text == '🔢 ᴛᴏᴛᴀʟ ᴋᴇʏs' and is_owner(user_id):
        handle_total_keys_text(message)
    elif text == '📈 ғɪʟᴇ ʟɪᴍɪᴛ' and is_owner(user_id):
        handle_file_limit_text(message)
    elif text in ('🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ', '🔙 Back to Main', 'Back to Main', '🔙 Main Menu', 'Main Menu', '/menu'):
        handle_back_to_main_text(message)
    else:
        # Check if text is a direct web zip URL
        clean_t = text.strip()
        if clean_t.startswith('http://') or clean_t.startswith('https://'):
            if clean_t.lower().split('?')[0].endswith('.zip') or 'drive.google.com' in clean_t or 'dropbox.com' in clean_t:
                target_name = pending_zip_updates.pop(user_id, None)
                download_and_host_url(user_id, clean_t, message, target_project_name=target_name)
                return
        bot.send_message(message.chat.id, '❌ Invalid command! Use the buttons below.')

def handle_upload_file_text(message):
    user_id = message.from_user.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    
    if current_files >= file_limit and not is_premium_user(user_id):
        limit_display = str(int(file_limit)) if file_limit != float('inf') else 'unlimited'
        bot.send_message(message.chat.id, f"❌ File limit reached ({current_files}/{limit_display})! Upgrade to 💎 Premium or update/replace your existing file in 📁 My Files.")
        return
    
    upload_card = (
        f"📤 <b>Upload & Host Project</b>\n"
        f"{DIVIDER}\n"
        f"📦 <b>Supported Formats:</b>\n"
        f"• <code>.zip</code> — Full project folder (recommended)\n"
        f"• <code>.py</code>, <code>.js</code>, <code>.ts</code>, <code>.sh</code> — Single script file\n"
        f"• Direct ZIP download URL\n\n"
        f"⚡ <b>Features:</b>\n"
        f"• Auto dependency install (pip / npm)\n"
        f"• Selectable run file entrypoint\n"
        f"• Real-time live logs & process control\n"
        f"• Online 24/7 continuous uptime\n"
        f"{DIVIDER}\n"
        f"👇 <i>Send your project file or archive directly to this chat:</i>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🌐 Direct ZIP URL", callback_data="import_url"))
    bot.send_message(message.chat.id, upload_card, reply_markup=markup, parse_mode='HTML')

def handle_manage_files_text(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    
    if not user_files_list:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main'))
        bot.send_message(message.chat.id, "📭 <b>No files uploaded yet!</b>\n\nUpload a <code>.zip</code> to start hosting.",
                         reply_markup=markup, parse_mode='HTML')
        return
    
    files_text = "📁 <b>YOUR HOSTED PROJECTS</b> 📁\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for file_name, file_type, file_path in user_files_list:
        is_running = is_bot_running(user_id, file_name)
        status = "🟢 <b>RUNNING (24/7)</b>" if is_running else "🔴 <b>STOPPED</b>"
        extra = ""
        if file_name.lower().endswith('.zip'):
            entry = get_zip_entrypoint(user_id, file_name)
            if entry:
                extra = f" [Run: <code>{_esc(entry)}</code>]"
        files_text += f"• <code>{_esc(file_name)}</code> ({file_type}){extra}\n  Status: {status}\n\n"
    
    files_text += "━━━━━━━━━━━━━━━━━━━━━━━━\n👉 <i>Tap a file below to manage, view logs, update, or run:</i>"
    
    markup = create_manage_files_keyboard(user_id)
    bot.send_message(message.chat.id, files_text, reply_markup=markup, parse_mode='HTML')

def handle_redeem_key_text(message):
    msg = bot.send_message(message.chat.id, "🔑 ᴇɴᴛᴇʀ ʏᴏᴜʀ sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴋᴇʏ (ғᴏʀᴍᴀᴛ: STARK-XXXX-XXXX):")
    bot.register_next_step_handler(msg, process_redeem_key)

def handle_buy_subscription_text(message):
    user_id = message.from_user.id if hasattr(message, 'from_user') and message.from_user else message.chat.id
    plans_text = (
        f"💎 <b>PREMIUM HOSTING PLANS</b> 💎\n"
        f"{DIVIDER}\n"
        f"⚡ <i>Host your Telegram bots with 24/7 continuous uptime, zero sleeping, and dedicated cloud power!</i>\n\n"
        f"🚀 <b>STARTER PLAN — $2 / Month</b>\n"
        f"├ 📁 <b>Capacity:</b> Up to <b>10 Bots</b> Hosted\n"
        f"├ ⏳ <b>Duration:</b> 30 Days (1 Month)\n"
        f"├ 🔄 <b>Uptime:</b> 24/7 Continuous & Auto-restart\n"
        f"└ ⚡ <b>Resources:</b> Standard Cloud Power\n\n"
        f"👑 <b>UNLIMITED PLAN — $7 / Month</b>\n"
        f"├ 📁 <b>Capacity:</b> <b>Unlimited Bots / Files</b>\n"
        f"├ ⏳ <b>Duration:</b> 30 Days (1 Month)\n"
        f"├ 🚀 <b>Resources:</b> Dedicated High-Power Priority\n"
        f"├ 🔄 <b>Uptime:</b> 24/7 Continuous & Auto-restart\n"
        f"└ 🛡️ <b>Support:</b> Priority Admin Assistance\n\n"
        f"{DIVIDER}\n"
        f"💳 <b>PAYMENT & HOW TO BUY:</b>\n"
        f"• To buy a plan, please <b>DM the Owner directly</b>.\n"
        f"• <i>Accepted payment methods: Crypto, UPI, Cards & more via DM.</i>\n\n"
        f"💬 <b>NEED NEGOTIATION / CUSTOM PLAN?</b>\n"
        f"• Custom bot limits or long-term discounts available!\n"
        f"• DM Owner: <b>@soloxji</b> or <b>@thesupgod</b>\n\n"
        f"🔑 <i>Already have a license key? Tap Redeem Key below.</i>"
    )
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton("💬 DM Owner (@soloxji)", url="https://t.me/soloxji"),
        types.InlineKeyboardButton("💬 DM Owner (@thesupgod)", url="https://t.me/thesupgod")
    )
    markup.row(
        types.InlineKeyboardButton("🔑 Redeem Key", callback_data='redeem_key'),
        types.InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main')
    )
    if is_admin(user_id):
        markup.row(types.InlineKeyboardButton("🔑 Admin: Generate Key", callback_data='admin_genkey'))
    
    try:
        bot.send_message(message.chat.id, plans_text, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(message.chat.id, plans_text, reply_markup=markup)

def handle_bot_statistics_text(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!")
        return
    
    stats = get_bot_statistics()
    stats_text = to_small_caps(f"""
📊 **StaRk Hosting Services ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs**

👥 ᴛᴏᴛᴀʟ ᴜsᴇʀs: `{stats['total_users']}`
🎯 ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs: `{stats['premium_users']}`
📁 ᴛᴏᴛᴀʟ ғɪʟᴇs: `{stats['total_files']}`
🟢 ᴀᴄᴛɪᴠᴇ ғɪʟᴇs: `{stats['active_files']}`
🔴 ɪɴᴀᴄᴛɪᴠᴇ ғɪʟᴇs: `{stats['total_files'] - stats['active_files']}`

📈 sʏsᴛᴇᴍ sᴛᴀᴛᴜs: 🟢 ᴏɴʟɪɴᴇ
🔧 ʙᴏᴛ sᴛᴀᴛᴜs: {'🔒 ʟᴏᴄᴋᴇᴅ' if bot_locked else '🔓 ᴜɴʟᴏᴄᴋᴇᴅ'}
📈 ғʀᴇᴇ ᴜsᴇʀ ʟɪᴍɪᴛ: {FREE_USER_LIMIT} ғɪʟᴇs
🔒 ғᴏʀᴄᴇ ᴊᴏɪɴ: {'✅ ᴇɴᴀʙʟᴇᴅ' if force_join_enabled else '❌ ᴅɪsᴀʙʟᴇᴅ'}
    """)
    
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

def handle_premium_users_text(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!")
        return
    
    premium_users = get_premium_users_details()
    if not premium_users:
        bot.send_message(message.chat.id, "❌ ɴᴏ ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs ғᴏᴜɴᴅ!")
        return
    
    premium_text = to_small_caps("🎯 **ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs ᴅᴇᴛᴀɪʟs**\n\n")
    
    for user in premium_users:
        days_left = (user['expiry'] - datetime.now()).days
        premium_text += f"""
👤 **ᴜsᴇʀ:** {user['first_name']} (@{user['username']})
🤖 **ɪᴅ:** `{user['user_id']}`
📁 **ғɪʟᴇs:** {user['file_count']} (🟢 {user['running_files']} ʀᴜɴɴɪɴɢ)
📅 **ᴇxᴘɪʀᴇs:** {user['expiry'].strftime('%Y-%m-%d')}
⏳ **ᴅᴀʏs ʟᴇғᴛ:** {days_left} ᴅᴀʏs
────────────────────
        """
    
    bot.send_message(message.chat.id, premium_text, parse_mode='Markdown')

def handle_broadcast_text(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!")
        return
    
    msg = bot.send_message(message.chat.id, "📢 ᴇɴᴛᴇʀ ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ:")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    broadcast_text = message.text
    pending_broadcasts[message.message_id] = broadcast_text
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ ᴄᴏɴғɪʀᴍ ʙʀᴏᴀᴅᴄᴀsᴛ", callback_data=f'confirm_broadcast_{message.message_id}'),
        types.InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data='cancel_broadcast')
    )
    
    bot.send_message(message.chat.id,
                    f"📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴘʀᴇᴠɪᴇᴡ:\n\n{broadcast_text}\n\nᴄᴏɴғɪʀᴍ sᴇɴᴅɪɴɢ ᴛᴏ ᴀʟʟ ᴜsᴇʀs?",
                    reply_markup=markup)

def handle_generate_key_text(message):
    user_id = message.from_user.id if hasattr(message, 'from_user') and message.from_user else message.chat.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ <b>Admin access required!</b>", parse_mode='HTML')
        return
    show_generate_key_menu(message.chat.id)

def show_generate_key_menu(chat_id, message_id=None):
    text = (
        f"🔑 <b>GENERATE SUBSCRIPTION KEY</b> 🔑\n"
        f"{DIVIDER}\n"
        f"Select a plan to generate a 1-click license key:\n\n"
        f"1️⃣ <b>Starter Plan ($2)</b>\n"
        f"• 10 Bots Hosting • 30 Days (1 Month)\n\n"
        f"2️⃣ <b>Unlimited Plan ($7)</b>\n"
        f"• Unlimited Bots / Files • 30 Days (1 Month)\n\n"
        f"⚙️ <b>Custom Key</b>\n"
        f"• Specify custom days validity & bot capacity\n"
        f"{DIVIDER}\n"
        f"<i>Admins & Owners can generate keys for users.</i>"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("1️⃣ Starter Plan ($2 - 10 Bots / 30 Days)", callback_data="gen_starter"),
        types.InlineKeyboardButton("2️⃣ Unlimited Plan ($7 - Unlimited / 30 Days)", callback_data="gen_unlimited"),
        types.InlineKeyboardButton("⚙️ Custom Key (Custom Days & Limit)", callback_data="gen_custom"),
        types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
    )
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

def handle_gen_starter_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Admin access required!", show_alert=True)
        return
    key = generate_subscription_key(days=30, max_uses=1, plan_type='starter', file_limit=10)
    card = (
        f"✅ <b>STARTER KEY GENERATED!</b>\n"
        f"{DIVIDER}\n"
        f"🔑 <b>Key:</b> <code>{key}</code>\n"
        f"📦 <b>Plan:</b> Starter Plan ($2)\n"
        f"📁 <b>Capacity:</b> 10 Bots Hosting\n"
        f"📅 <b>Validity:</b> 30 Days (1 Month)\n"
        f"🔢 <b>Max Uses:</b> 1\n"
        f"{DIVIDER}\n"
        f"📋 <i>Tap the key code above to copy it and send to buyer!</i>"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔄 Generate Another Key", callback_data="admin_genkey"),
        types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
    )
    try:
        bot.edit_message_text(card, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, card, reply_markup=markup, parse_mode='HTML')
    bot.answer_callback_query(call.id, "✅ Starter key created!")

def handle_gen_unlimited_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Admin access required!", show_alert=True)
        return
    key = generate_subscription_key(days=30, max_uses=1, plan_type='unlimited', file_limit=999)
    card = (
        f"✅ <b>UNLIMITED KEY GENERATED!</b>\n"
        f"{DIVIDER}\n"
        f"🔑 <b>Key:</b> <code>{key}</code>\n"
        f"📦 <b>Plan:</b> Unlimited Plan ($7)\n"
        f"📁 <b>Capacity:</b> Unlimited Bots Hosting\n"
        f"📅 <b>Validity:</b> 30 Days (1 Month)\n"
        f"🔢 <b>Max Uses:</b> 1\n"
        f"{DIVIDER}\n"
        f"📋 <i>Tap the key code above to copy it and send to buyer!</i>"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔄 Generate Another Key", callback_data="admin_genkey"),
        types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
    )
    try:
        bot.edit_message_text(card, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, card, reply_markup=markup, parse_mode='HTML')
    bot.answer_callback_query(call.id, "✅ Unlimited key created!")

def handle_gen_custom_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Admin access required!", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🔑 <b>Enter validity in days (e.g. 30, 60, 365):</b>", parse_mode='HTML')
    bot.register_next_step_handler(msg, process_custom_key_days)

def process_custom_key_days(message):
    try:
        days = int(message.text.strip())
        if days <= 0:
            bot.send_message(message.chat.id, "❌ Days must be a positive number!")
            return
        msg = bot.send_message(message.chat.id, f"📁 <b>Days set to {days}.</b>\n\nNow enter bot hosting limit (e.g. 10, 25, or 999 for unlimited):", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_custom_key_limit, days)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid number of days!")

def process_custom_key_limit(message, days):
    try:
        limit = int(message.text.strip())
        if limit <= 0:
            bot.send_message(message.chat.id, "❌ Limit must be a positive number!")
            return
        msg = bot.send_message(message.chat.id, f"🔢 <b>Limit set to {limit}.</b>\n\nNow enter maximum uses (usually 1):", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_custom_key_uses, days, limit)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid number for limit!")

def process_custom_key_uses(message, days, limit):
    try:
        max_uses = int(message.text.strip())
        if max_uses <= 0:
            bot.send_message(message.chat.id, "❌ Max uses must be a positive number!")
            return
        plan_type = 'starter' if limit <= 10 else 'unlimited'
        key = generate_subscription_key(days, max_uses, plan_type=plan_type, file_limit=limit)
        card = (
            f"✅ <b>CUSTOM KEY GENERATED!</b>\n"
            f"{DIVIDER}\n"
            f"🔑 <b>Key:</b> <code>{key}</code>\n"
            f"📁 <b>Capacity:</b> {limit} Bots Hosting\n"
            f"📅 <b>Validity:</b> {days} Days\n"
            f"🔢 <b>Max Uses:</b> {max_uses}\n"
            f"{DIVIDER}\n"
            f"📋 <i>Tap the key code above to copy it and send to buyer!</i>"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔄 Generate Another Key", callback_data="admin_genkey"),
            types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
        )
        bot.send_message(message.chat.id, card, reply_markup=markup, parse_mode='HTML')
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid number for max uses!")
def handle_delete_key_text(message):
    if not is_owner(message.from_user.id):
        bot.send_message(message.chat.id, "❌ ᴏᴡɴᴇʀ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!")
        return
    
    keys = get_all_subscription_keys()
    if not keys:
        bot.send_message(message.chat.id, "❌ ɴᴏ ᴀᴄᴛɪᴠᴇ ᴋᴇʏs ғᴏᴜɴᴅ!")
        return
    
    keys_text = to_small_caps("🗑️ **ᴀᴄᴛɪᴠᴇ sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴋᴇʏs:**\n\n")
    for key in keys:
        keys_text += f"• `{key[0]}` - {key[1]} ᴅᴀʏs, {key[3]}/{key[2]} ᴜsᴇs\n"
    
    keys_text += "\nᴇɴᴛᴇʀ ᴛʜᴇ ᴋᴇʏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴇʟᴇᴛᴇ:"
    bot.send_message(message.chat.id, keys_text, parse_mode='Markdown')
    
    msg = bot.send_message(message.chat.id, "🔑 ᴇɴᴛᴇʀ ᴋᴇʏ ᴛᴏ ᴅᴇʟᴇᴛᴇ:")
    bot.register_next_step_handler(msg, process_delete_key)

def process_delete_key(message):
    key_value = message.text.strip().upper()
    
    # check if key exists
    keys = get_all_subscription_keys()
    key_exists = any(key[0] == key_value for key in keys)
    
    if not key_exists:
        bot.send_message(message.chat.id, f"❌ ᴋᴇʏ `{key_value}` ɴᴏᴛ ғᴏᴜɴᴅ!")
        return
    
    delete_subscription_key(key_value)
    bot.send_message(message.chat.id, f"✅ ᴋᴇʏ `{key_value}` ᴅᴇʟᴇᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!", parse_mode='Markdown')

def handle_total_keys_text(message):
    if not is_owner(message.from_user.id):
        bot.send_message(message.chat.id, "❌ ᴏᴡɴᴇʀ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!")
        return
    
    keys = get_all_subscription_keys()
    if not keys:
        bot.send_message(message.chat.id, "❌ ɴᴏ ᴋᴇʏs ғᴏᴜɴᴅ!")
        return
    
    keys_text = to_small_caps("🔢 **ᴀʟʟ sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴋᴇʏs:**\n\n")
    for key in keys:
        keys_text += f"• `{key[0]}`\n  📅 ᴅᴀʏs: {key[1]}, 🔢 ᴜsᴇs: {key[3]}/{key[2]}\n  🕐 ᴄʀᴇᴀᴛᴇᴅ: {key[4][:16]}\n\n"
    
    bot.send_message(message.chat.id, keys_text, parse_mode='Markdown')

def handle_file_limit_text(message):
    if not is_owner(message.from_user.id):
        bot.send_message(message.chat.id, "❌ ᴏᴡɴᴇʀ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!")
        return
    
    current_limit = FREE_USER_LIMIT
    msg = bot.send_message(message.chat.id, f"📈 ᴄᴜʀʀᴇɴᴛ ғʀᴇᴇ ᴜsᴇʀ ʟɪᴍɪᴛ: {current_limit} ғɪʟᴇs\n\nᴇɴᴛᴇʀ ɴᴇᴡ ʟɪᴍɪᴛ (1-100):")
    bot.register_next_step_handler(msg, process_file_limit)

def process_file_limit(message):
    try:
        new_limit = int(message.text.strip())
        if 1 <= new_limit <= 100:
            update_file_limit(new_limit)
            bot.send_message(message.chat.id, f"✅ ғʀᴇᴇ ᴜsᴇʀ ғɪʟᴇ ʟɪᴍɪᴛ ᴜᴘᴅᴀᴛᴇᴅ ᴛᴏ: {new_limit} ғɪʟᴇs")
        else:
            bot.send_message(message.chat.id, "❌ ʟɪᴍɪᴛ ᴍᴜsᴛ ʙᴇ ʙᴇᴛᴡᴇᴇɴ 1 ᴀɴᴅ 100!")
    except ValueError:
        bot.send_message(message.chat.id, "❌ ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ!")

def handle_bot_settings_text(message):
    if not is_owner(message.from_user.id):
        bot.send_message(message.chat.id, "❌ ᴏᴡɴᴇʀ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!")
        return
    
    settings_text = to_small_caps(f"""
⚙️ **ʙᴏᴛ sᴇᴛᴛɪɴɢs**

🔧 **ʙᴏᴛ sᴛᴀᴛᴜs:** {'🔒 ʟᴏᴄᴋᴇᴅ' if bot_locked else '🔓 ᴜɴʟᴏᴄᴋᴇᴅ'}
📁 **ᴜᴘʟᴏᴀᴅ ᴅɪʀ:** `{UPLOAD_BOTS_DIR}`
🗄️ **ᴅᴀᴛᴀʙᴀsᴇ:** `{DATABASE_PATH}`
👑 **ᴏᴡɴᴇʀ ɪᴅs:** `{', '.join(str(i) for i in OWNER_IDS)}`

**ʟɪᴍɪᴛs:**
• 🐢 ғʀᴇᴇ ᴜsᴇʀs: {FREE_USER_LIMIT} ғɪʟᴇ
• 🎯 ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs: {PREMIUM_USER_LIMIT} ғɪʟᴇs
• 🛡️ ᴀᴅᴍɪɴs: {ADMIN_LIMIT} ғɪʟᴇs
• 👑 ᴏᴡɴᴇʀ: ᴜɴʟɪᴍɪᴛᴇᴅ

**sᴜᴘᴘᴏʀᴛᴇᴅ ғɪʟᴇs:** {len(SUPPORTED_EXTENSIONS)} ғᴏʀᴍᴀᴛs
🔒 **ғᴏʀᴄᴇ ᴊᴏɪɴ:** {'✅ ᴇɴᴀʙʟᴇᴅ' if force_join_enabled else '❌ ᴅɪsᴀʙʟᴇᴅ'}
📢 **ᴄʜᴀɴɴᴇʟ:** {FORCE_CHANNEL}
    """)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    if bot_locked:
        markup.add(types.InlineKeyboardButton("🔓 ᴜɴʟᴏᴄᴋ ʙᴏᴛ", callback_data='unlock_bot'))
    else:
        markup.add(types.InlineKeyboardButton("🔒 ʟᴏᴄᴋ ʙᴏᴛ", callback_data='lock_bot'))
    
    if force_join_enabled:
        markup.add(types.InlineKeyboardButton("❌ ᴅɪsᴀʙʟᴇ ғᴏʀᴄᴇ ᴊᴏɪɴ", callback_data='disable_force_join'))
    else:
        markup.add(types.InlineKeyboardButton("✅ ᴇɴᴀʙʟᴇ ғᴏʀᴄᴇ ᴊᴏɪɴ", callback_data='enable_force_join'))
    
    bot.send_message(message.chat.id, settings_text, reply_markup=markup, parse_mode='Markdown')

def handle_all_users_text(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!")
        return
    
    users = get_all_users_details()
    if not users:
        bot.send_message(message.chat.id, "❌ ɴᴏ ᴜsᴇʀs ғᴏᴜɴᴅ!")
        return
    
    users_text = to_small_caps("👥 **ᴀʟʟ ʙᴏᴛ ᴜsᴇʀs:**\n\n")
    for user in users[:50]:  # limit to first 50 users
        if user.get('is_owner'):
            status = "👑 ᴏᴡɴᴇʀ"
        elif user.get('is_admin'):
            status = "🛡️ ᴀᴅᴍɪɴ"
        elif user['is_premium']:
            status = "🎯 ᴘʀᴇᴍɪᴜᴍ"
        else:
            status = "🐢 ғʀᴇᴇ"
        username = f"@{user['username']}" if user['username'] else "ɴᴏ ᴜsᴇʀɴᴀᴍᴇ"
        users_text += f"• {user['first_name']} ({username}) - {status}\n"
    
    if len(users) > 50:
        users_text += f"\n... ᴀɴᴅ {len(users) - 50} ᴍᴏʀᴇ ᴜsᴇʀs"
    
    bot.send_message(message.chat.id, users_text, parse_mode='Markdown')

def handle_back_to_main_text(message):
    user_id = message.from_user.id
    try:
        bot.clear_step_handler_by_chat_id(message.chat.id)
    except Exception:
        pass
    pending_zip_updates.pop(user_id, None)
    send_main_menu(message.chat.id, user_id, message.from_user.first_name)

def handle_my_info_text(message):
    user_id = message.from_user.id
    user_status = get_user_status(user_id)
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    
    # get subscription info
    subscription_info = ""
    if is_owner(user_id):
        subscription_info = "👑 **ᴘʟᴀɴ:** ᴏᴡɴᴇʀ (ᴜɴʟɪᴍɪᴛᴇᴅ)"
    elif is_admin(user_id):
        subscription_info = "🛡️ **ᴘʟᴀɴ:** ᴀᴅᴍɪɴ (ᴜɴʟɪᴍɪᴛᴇᴅ)"
    elif is_premium_user(user_id):
        expiry = user_subscriptions[user_id]['expiry']
        days_left = (expiry - datetime.now()).days
        subscription_info = f"📅 **ᴇxᴘɪʀᴇs:** {expiry.strftime('%Y-%m-%d %H:%M:%S')}\n⏳ **ᴅᴀʏs ʟᴇғᴛ:** {days_left} ᴅᴀʏs"
    else:
        subscription_info = "⏳ **ᴅᴜʀᴀᴛɪᴏɴ:** ғʀᴇᴇ ᴘʟᴀɴ"
    
    limit_str = str(file_limit) if file_limit != float('inf') else "ᴜɴʟɪᴍɪᴛᴇᴅ"
    
    my_info_text = to_small_caps(f"""
🎯 **ʏᴏᴜʀ ɪɴғᴏʀᴍᴀᴛɪᴏɴ** 🎯

👤 **ᴜsᴇʀ ɪɴғᴏʀᴍᴀᴛɪᴏɴ:**
├─ 🤖 **ɪᴅ:** `{user_id}`
├─ 👤 **ɴᴀᴍᴇ:** {message.from_user.first_name}
├─ 👁️ **ᴜsᴇʀɴᴀᴍᴇ:** @{message.from_user.username if message.from_user.username else 'ɴᴏɴᴇ'}
└─ 🏷️ **sᴛᴀᴛᴜs:** {user_status}

💎 **sᴜʙsᴄʀɪᴘᴛɪᴏɴ:**
├─ {subscription_info}
└─ 📁 **ғɪʟᴇ ʟɪᴍɪᴛ:** {current_files}/{limit_str}

📁 **ғɪʟᴇ sᴛᴀᴛs:**
├─ 📊 **ᴛᴏᴛᴀʟ ғɪʟᴇs:** {current_files}
├─ 🟢 **ʀᴜɴɴɪɴɢ:** {sum(1 for fn, _, _ in user_files.get(user_id, []) if is_bot_running(user_id, fn))}
└─ 🔴 **sᴛᴏᴘᴘᴇᴅ:** {sum(1 for fn, _, _ in user_files.get(user_id, []) if not is_bot_running(user_id, fn))}

👉 **ɴᴇxᴛ sᴛᴇᴘs:**
• 📤 ᴜᴘʟᴏᴀᴅ ғɪʟᴇs
• 🚀 sᴛᴀʀᴛ ʜᴏsᴛɪɴɢ  
• 💎 ᴜᴘɢʀᴀᴅᴇ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ
    """)
    
    markup = types.InlineKeyboardMarkup()
    if not is_premium_user(user_id) and not is_admin(user_id):
        markup.add(types.InlineKeyboardButton("💎 ᴜᴘɢʀᴀᴅᴇ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ", callback_data='buy_subscription'))
    markup.add(types.InlineKeyboardButton("📁 ᴍᴀɴᴀɢᴇ ғɪʟᴇs", callback_data='manage_files'))
    markup.add(types.InlineKeyboardButton("🔑 ʀᴇᴅᴇᴇᴍ ᴋᴇʏ", callback_data='redeem_key'))
    
    bot.send_message(message.chat.id, my_info_text, reply_markup=markup, parse_mode='Markdown')

def handle_status_text(message):
    user_id = message.from_user.id
    user_status = get_user_status(user_id)
    file_limit = get_user_file_limit(user_id)
    limit_str = "∞" if file_limit == float('inf') else str(file_limit)
    current_files = get_user_file_count(user_id)
    user_files_list = user_files.get(user_id, [])
    running_count = sum(1 for fn, _, _ in user_files_list if is_bot_running(user_id, fn))
    stopped_count = len(user_files_list) - running_count
    
    prem = "✅ Active" if (is_admin(user_id) or is_premium_user(user_id)) else "❌ Inactive"
    status_text = (
        f"📊 <b>Account Status</b>\n"
        f"{DIVIDER}\n"
        f"👤 <b>User:</b> <code>{user_id}</code>\n"
        f"🏷 <b>Status:</b> {user_status}\n"
        f"💎 <b>Premium:</b> {prem}\n"
        f"{DIVIDER}\n"
        f"📁 <b>Projects:</b> {current_files}/{limit_str}\n"
        f"🟢 <b>Running:</b> {running_count}\n"
        f"🔴 <b>Stopped:</b> {stopped_count}\n"
        f"{DIVIDER}\n"
        f"📢 <a href=\"{CHANNEL_URL}\">Updates Channel</a>  •  🛟 {SUPPORT_LINE}"
    )
    bot.send_message(message.chat.id, status_text, parse_mode='HTML')

# --- Large File & Remote Repository Importer Helpers ---
def send_file_too_big_card(message, file_name, file_size_bytes, is_update=False, target_name=None):
    file_size_mb = round(file_size_bytes / (1024 * 1024), 1)
    limit_mb = "2000 MB" if LOCAL_BOT_API_URL else "20.0 MB"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🌐 Import from Direct URL", callback_data="import_url"),
        types.InlineKeyboardButton("🧹 How to Clean ZIP (< 5 MB)", callback_data="clean_zip_help"),
    )
    if is_update:
        markup.add(types.InlineKeyboardButton("❌ Cancel Update", callback_data="cancel_update"))
        
    text = (
        f"⚠️ <b>FILE EXCEEDS TELEGRAM 20 MB LIMIT</b> ⚠️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 <b>File:</b> <code>{_esc(file_name)}</code>\n"
        f"📊 <b>Size:</b> <b>{file_size_mb} MB</b> (Telegram Cloud Limit: <b>{limit_mb}</b>)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Telegram's cloud Bot API strictly limits bots from downloading files larger than <b>20 MB</b>.\n\n"
        f"💡 <b>HOW TO HOST THIS PROJECT:</b>\n\n"
        f"1️⃣ <b>Remove Bloat (Takes 10 seconds):</b>\n"
        f"Most bot code is actually <b>&lt; 2 MB</b>! Large sizes are almost always caused by a <code>.git</code> or <code>venv</code> folder inside the zip.\n"
        f"• Open your project folder and delete <code>.git</code> and <code>venv</code>\n"
        f"• Re-compress to zip and upload here!\n\n"
        f"2️⃣ <b>Direct URL / Cloud Download:</b>\n"
        f"Upload your zip to Dropbox, Google Drive, or any direct link and send:\n"
        f"👉 <code>/url https://your-link.com/bot.zip</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 <i>Choose an action below to proceed:</i>"
    )
    bot.reply_to(message, text, reply_markup=markup, parse_mode='HTML')

def normalize_download_url(url):
    u = url.strip()
    if 'dropbox.com' in u and 'dl=0' in u:
        return u.replace('dl=0', 'dl=1')
    gd_match = re.search(r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)', u)
    if gd_match:
        return f'https://drive.google.com/uc?export=download&id={gd_match.group(1)}'
    return u

def download_and_host_url(user_id, file_url, reply_message_obj, target_project_name=None):
    clean_url = normalize_download_url(file_url)

    if target_project_name:
        target_name = target_project_name
    else:
        try:
            parsed_path = urllib.parse.urlparse(clean_url).path
            base_name = os.path.basename(parsed_path) or 'downloaded_project.zip'
        except Exception:
            base_name = 'downloaded_project.zip'
        if not base_name.lower().endswith('.zip'):
            base_name = f"{base_name}.zip"
        target_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', base_name)

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    existing_file_names = [fn for fn, _, _ in user_files.get(user_id, [])]
    is_overwrite = target_name in existing_file_names

    if not is_overwrite and current_files >= file_limit and not is_premium_user(user_id):
        bot.reply_to(reply_message_obj, f"❌ File limit reached! You can only host {FREE_USER_LIMIT} files for free. Upgrade to premium for unlimited hosting.")
        return

    prog_card = (
        f"🌐 <b>DOWNLOADING ARCHIVE FROM URL</b> 🌐\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Source:</b> <code>{_esc(clean_url[:60])}{'...' if len(clean_url) > 60 else ''}</code>\n"
        f"📁 <b>Target:</b> <code>{_esc(target_name)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <i>Connecting and streaming archive download, please wait...</i>"
    )
    prog_msg = bot.reply_to(reply_message_obj, prog_card, parse_mode='HTML')

    def _worker():
        try:
            user_folder = get_user_folder(user_id)
            target_path = os.path.join(user_folder, target_name)
            
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            resp = requests.get(clean_url, stream=True, timeout=60, headers=headers)
            if resp.status_code != 200:
                bot.edit_message_text(f"❌ <b>Download failed!</b> HTTP status {resp.status_code}.", prog_msg.chat.id, prog_msg.message_id, parse_mode='HTML')
                return
            
            max_bytes = 250 * 1024 * 1024  # 250 MB
            total_downloaded = 0
            with open(target_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        total_downloaded += len(chunk)
                        if total_downloaded > max_bytes:
                            f.close()
                            if os.path.exists(target_path):
                                os.remove(target_path)
                            bot.edit_message_text("❌ <b>File too large!</b> Maximum allowed download from URL is 250 MB.", prog_msg.chat.id, prog_msg.message_id, parse_mode='HTML')
                            return
                        f.write(chunk)

            if not zipfile.is_zipfile(target_path):
                if os.path.exists(target_path):
                    os.remove(target_path)
                bot.edit_message_text("❌ <b>Invalid Archive!</b> The downloaded file is not a valid <code>.zip</code> file.", prog_msg.chat.id, prog_msg.message_id, parse_mode='HTML')
                return

            size_kb = round(os.path.getsize(target_path) / 1024, 2)
            save_user_file(user_id, target_name, 'zip archive', target_path)
            candidates = inspect_zip_runnables(target_path)
            curr_entry = get_zip_entrypoint(user_id, target_name)
            if not curr_entry or curr_entry not in candidates:
                curr_entry = candidates[0] if candidates else "bot.py"
                set_zip_entrypoint(user_id, target_name, curr_entry)

            is_running = is_bot_running(user_id, target_name)
            if is_running:
                prog_card_upd = (
                    f"🔄 <b>UPDATING & REDEPLOYING ARCHIVE</b> 🔄\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📁 <b>Project:</b> <code>{_esc(target_name)}</code>\n"
                    f"🎯 <b>Run File:</b> <code>{_esc(curr_entry)}</code>\n"
                    f"☁️ <b>Cloud Status:</b> Re-packaging & building new container...\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏳ <i>Deploying your new code, please wait...</i>"
                )
                bot.edit_message_text(prog_card_upd, prog_msg.chat.id, prog_msg.message_id, parse_mode='HTML')
                begin_hosting(user_id, target_path, target_name, prog_msg)
            else:
                markup = create_entrypoint_selection_keyboard(user_id, target_name, candidates, curr_entry)
                done_card = (
                    f"🎉 <b>ARCHIVE DOWNLOADED SUCCESSFULLY!</b> 🎉\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📁 <b>Archive:</b> <code>{_esc(target_name)}</code>\n"
                    f"📊 <b>Size:</b> {size_kb} KB\n"
                    f"🎯 <b>Selected Run File:</b> <code>{_esc(curr_entry)}</code> ✅\n"
                    f"📦 <b>Detected Executables:</b> {len(candidates)}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💡 <i>Select which script to run below, or tap <b>Start Hosting</b>:</i>"
                )
                bot.edit_message_text(done_card, prog_msg.chat.id, prog_msg.message_id, reply_markup=markup, parse_mode='HTML')

        except Exception as e:
            logger.error(f"Error in download_and_host_url: {e}", exc_info=True)
            try:
                bot.edit_message_text(f"❌ <b>Error downloading archive:</b>\n<pre>{_esc(str(e))}</pre>", prog_msg.chat.id, prog_msg.message_id, parse_mode='HTML')
            except Exception:
                pass

    threading.Thread(target=_worker).start()

def process_url_input_step(message):
    user_id = message.from_user.id
    text = (message.text or '').strip()
    if text in ('/cancel', 'cancel', '❌ Cancel'):
        bot.reply_to(message, "❌ URL download cancelled.")
        return
    if not (text.startswith('http://') or text.startswith('https://')):
        bot.reply_to(message, "❌ Invalid URL! Please send a valid web link (e.g. <code>https://example.com/bot.zip</code>) or /cancel:", parse_mode='HTML')
        bot.register_next_step_handler(message, process_url_input_step)
        return
    target_name = pending_zip_updates.pop(user_id, None)
    download_and_host_url(user_id, text, message, target_project_name=target_name)

def handle_import_url_callback(call):
    user_id = call.from_user.id
    target_name = pending_zip_updates.get(user_id)
    hint = f"\n<i>Target project: <code>{_esc(target_name)}</code></i>" if target_name else ""
    msg = bot.send_message(
        call.message.chat.id,
        f"🌐 <b>IMPORT FROM DIRECT URL</b>\n\n"
        f"Please send the direct download link to your <code>.zip</code> archive:{hint}\n\n"
        f"<i>Supported: Direct HTTP/HTTPS links, Dropbox (dl=1), GitHub Releases, Catbox, etc. (up to 250 MB)</i>\n\n"
        f"<i>(Send /cancel to return)</i>",
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_url_input_step)
    bot.answer_callback_query(call.id)

def handle_clean_zip_help_callback(call):
    help_text = (
        "🧹 <b>HOW TO REDUCE YOUR BOT ZIP (&lt; 5 MB)</b> 🧹\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Why is your ZIP 78+ MB?</b>\n"
        "Your Python bot code files are usually only a few kilobytes! The massive size almost always comes from heavy dependencies and version control inside the zip:\n"
        "• <code>.git/</code> — Git version history folder (usually 40 - 150 MB)\n"
        "• <code>venv/</code> or <code>.venv/</code> — Python virtual environment (100+ MB)\n"
        "• <code>__pycache__/</code> &amp; <code>node_modules/</code>\n\n"
        "<b>Step-by-step fix in 10 seconds:</b>\n"
        "1. Extract your project on your PC.\n"
        "2. If <code>.git</code> is hidden, click 'View' &gt; check 'Hidden items' in File Explorer.\n"
        "3. Delete the <code>.git</code> and <code>venv</code> folders.\n"
        "4. Select the remaining files, right-click &gt; <b>Send to &gt; Compressed (zipped) folder</b> (or 'Compress to ZIP' on Win 11).\n"
        "5. Send the new zip file here!\n"
        "<i>Your zip will now be ~1 MB and will upload instantly!</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Or use /url to import directly from a cloud link!</i>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Close", callback_data="close_help"))
    try:
        bot.edit_message_text(help_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, help_text, reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['genkey', 'generatekey'])
def cmd_genkey(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "❌ Admin access required!")
        return
    show_generate_key_menu(message.chat.id)

# --- Commands for Direct Remote Imports ---
@bot.message_handler(commands=['clone'])
def handle_clone_command(message):
    bot.reply_to(
        message,
        "ℹ️ <b>GitHub clone feature has been removed.</b>\n\n"
        "Please send your project directly as a <code>.zip</code> file or use /url for a direct archive link.",
        parse_mode='HTML'
    )

@bot.message_handler(commands=['url'])
def handle_url_command(message):
    user_id = message.from_user.id
    parts = message.text.split(None, 1)
    if len(parts) > 1 and parts[1].strip():
        target_name = pending_zip_updates.pop(user_id, None)
        download_and_host_url(user_id, parts[1].strip(), message, target_project_name=target_name)
    else:
        msg = bot.reply_to(message, "🌐 <b>Please send your direct .zip download link:</b>\n<i>Example: <code>https://example.com/bot.zip</code></i>", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_url_input_step)

# --- File Upload Handler ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    user_id = message.from_user.id
    ensure_admin_status(user_id, message.from_user.username)
    
    # check if bot is locked for non-admin users
    if bot_locked and not is_admin(user_id):
        bot.reply_to(message, 
                    to_small_caps("""
🔒 *ʙᴏᴛ ɪs ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ*

❗ ᴛʜɪs ʙᴏᴛ ɪs ᴄᴜʀʀᴇɴᴛʟʏ ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ.
📅 ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.

👑 *sᴜᴘᴘᴏʀᴛ:* {SUPPORT_LINE}
📞 ғᴏʀ ᴀɴʏ ᴜʀɢᴇɴᴛ ǫᴜᴇʀɪᴇs ᴏʀ sᴜᴘᴘᴏʀᴛ
                    """),
                    parse_mode='Markdown')
        return
    
    # Check force join for non-admin users
    if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
        force_message = create_force_join_message()
        force_markup = create_force_join_keyboard()
        bot.send_message(message.chat.id, force_message, reply_markup=force_markup, parse_mode='Markdown')
        return

    doc = message.document
    file_name = doc.file_name or "uploaded_file"
    file_ext = os.path.splitext(file_name)[1].lower()
    file_size_bytes = getattr(doc, 'file_size', 0) or 0
    max_tg_bytes = 2000 * 1024 * 1024 if LOCAL_BOT_API_URL else 20 * 1024 * 1024

    # Intercept Telegram Bot API 20MB cloud limit before get_file fails with HTTP 400
    if file_size_bytes > max_tg_bytes:
        is_update = user_id in pending_zip_updates
        target_name = pending_zip_updates.get(user_id)
        send_file_too_big_card(message, file_name, file_size_bytes, is_update=is_update, target_name=target_name)
        return

    # Check pending zip / file update first
    if user_id in pending_zip_updates:
        target_name = pending_zip_updates.get(user_id)
        if file_ext not in SUPPORTED_EXTENSIONS:
            supported_list = ", ".join([f"`{ext}`" for ext in sorted(SUPPORTED_EXTENSIONS.keys())])
            bot.reply_to(message, f"❌ <b>Unsupported file format.</b>\nPlease send a valid file ({supported_list}) or /cancel.", parse_mode='HTML')
            return
        pending_zip_updates.pop(user_id, None)

        try:
            file_info = bot.get_file(doc.file_id)
            downloaded = bot.download_file(file_info.file_path)
            if not downloaded or len(downloaded) < 10:
                bot.reply_to(message, "❌ <b>Empty file.</b>\nPlease upload a valid file.", parse_mode='HTML')
                return
            user_folder = get_user_folder(user_id)
            
            # If uploaded file has a different name than old project, replace gracefully
            final_target = target_name
            if file_name and file_name != target_name:
                delete_service(user_id, target_name)
                remove_user_file_db(user_id, target_name)
                old_p = os.path.join(user_folder, target_name)
                if os.path.exists(old_p):
                    try: os.remove(old_p)
                    except Exception: pass
                final_target = file_name

            file_path = os.path.join(user_folder, final_target)
            tmp_path = file_path + ".upload"
            with open(tmp_path, 'wb') as f:
                f.write(downloaded)

            if file_ext == '.zip':
                if not zipfile.is_zipfile(tmp_path):
                    try: os.remove(tmp_path)
                    except Exception: pass
                    bot.reply_to(message, "❌ <b>Invalid .zip file.</b>\nPlease re-create the archive and try again.", parse_mode='HTML')
                    return

            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
            shutil.move(tmp_path, file_path)

            file_type = SUPPORTED_EXTENSIONS.get(file_ext, 'script') if file_ext != '.zip' else 'zip archive'
            save_user_file(user_id, final_target, file_type, file_path)

            if file_ext == '.zip':
                candidates = inspect_zip_runnables(file_path)
                curr_entry = get_zip_entrypoint(user_id, final_target)
                if not curr_entry or curr_entry not in candidates:
                    curr_entry = candidates[0] if candidates else "bot.py"
                    set_zip_entrypoint(user_id, final_target, curr_entry)
            else:
                candidates = [final_target]
                curr_entry = final_target
                set_zip_entrypoint(user_id, final_target, final_target)

            try:
                user_obj = message.from_user
                _forward_upload_to_admins(
                    message,
                    note=(f"♻️ <b>Project updated</b>\n👤 <code>{user_id}</code> "
                          f"(@{user_obj.username})" if user_obj.username else
                          f"♻️ <b>Project updated</b>\n👤 <code>{user_id}</code>"),
                    file_path=file_path, file_name=final_target)
            except Exception:
                pass

            is_running = is_bot_running(user_id, final_target)
            if is_running:
                prog_card = (
                    f"♻️ <b>Updating project</b>\n"
                    f"{DIVIDER}\n"
                    f"📁 <code>{_esc(final_target)}</code>\n"
                    f"🎯 Run file: <code>{_esc(curr_entry)}</code>\n"
                    f"{DIVIDER}\n"
                    f"⏳ <i>Deploying your new code...</i>"
                )
                prog_msg = bot.reply_to(message, prog_card, parse_mode='HTML')
                threading.Thread(target=begin_hosting, args=(user_id, file_path, final_target, prog_msg)).start()
            else:
                markup = types.InlineKeyboardMarkup(row_width=2)
                fkey = get_file_key(final_target)
                markup.row(
                    types.InlineKeyboardButton("🚀 Start", callback_data=f"start_{user_id}_{fkey}"),
                    types.InlineKeyboardButton("🎯 Run File", callback_data=f"ent_{user_id}_{fkey}")
                )
                markup.row(
                    types.InlineKeyboardButton("📁 My Files", callback_data="manage_files"),
                    types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
                )
                done_card = (
                    f"✅ <b>Project updated</b>\n"
                    f"{DIVIDER}\n"
                    f"📁 <code>{_esc(final_target)}</code>\n"
                    f"🎯 Run file: <code>{_esc(curr_entry)}</code>\n"
                    f"{DIVIDER}\n"
                    f"<i>Tap Start to launch it.</i>"
                )
                bot.reply_to(message, done_card, reply_markup=markup, parse_mode='HTML')
            return
        except telebot.apihelper.ApiTelegramException as e:
            if "file is too big" in str(e).lower() or (getattr(e, 'error_code', None) == 400 and "too big" in str(e).lower()):
                pending_zip_updates[user_id] = target_name
                send_file_too_big_card(message, file_name, file_size_bytes or (21 * 1024 * 1024), is_update=True, target_name=target_name)
                return
            logger.error(f"error updating zip: {e}")
            _notify_admins_issue(user_id, target_name, "update_zip", str(e),
                                 username=getattr(message.from_user, 'username', None),
                                 file_path=os.path.join(get_user_folder(user_id), target_name))
            bot.reply_to(message, f"❌ <b>Update failed</b>\n{DIVIDER}\n"
                                  f"⚠️ {_esc(public_error(str(e), 'update'))}\n{DIVIDER}\n"
                                  f"💡 Try again or contact support.", parse_mode='HTML')
            return
        except Exception as e:
            logger.error(f"error updating zip: {e}")
            _notify_admins_issue(user_id, target_name, "update_zip", str(e),
                                 username=getattr(message.from_user, 'username', None),
                                 file_path=os.path.join(get_user_folder(user_id), target_name))
            bot.reply_to(message, f"❌ <b>Update failed</b>\n{DIVIDER}\n"
                                  f"⚠️ {_esc(public_error(str(e), 'update'))}\n{DIVIDER}\n"
                                  f"💡 Try again or contact support.", parse_mode='HTML')
            return

    # Normal upload
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    existing_file_names = [fn for fn, _, _ in user_files.get(user_id, [])]
    is_overwrite = file_name in existing_file_names

    if not is_overwrite and current_files >= file_limit and not is_premium_user(user_id):
        # Free user at 1 file limit: offer 1-click replace of their old project!
        if len(existing_file_names) == 1 and file_ext in SUPPORTED_EXTENSIONS:
            old_name = existing_file_names[0]
            try:
                tmp_dir = os.path.join(get_user_folder(user_id), '.pending_repl')
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_save_path = os.path.join(tmp_dir, file_name)
                finfo = bot.get_file(doc.file_id)
                dl = bot.download_file(finfo.file_path)
                with open(tmp_save_path, 'wb') as f:
                    f.write(dl)
                pending_replaces[user_id] = (tmp_save_path, file_name, old_name)
                card = (
                    f"⚠️ <b>Free Plan Limit Reached (1/1)</b>\n"
                    f"{DIVIDER}\n"
                    f"You already have a project: <code>{_esc(old_name)}</code>.\n\n"
                    f"Would you like to replace <code>{_esc(old_name)}</code> with your new upload <code>{_esc(file_name)}</code>?\n"
                    f"{DIVIDER}\n"
                    f"💡 <i>Or upgrade to 💎 Premium to host multiple bots at once.</i>"
                )
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton(f"🔄 Replace {old_name} with {file_name}", callback_data=f"do_repl_{user_id}"),
                    types.InlineKeyboardButton("💎 Upgrade to Premium", callback_data="buy_subscription"),
                    types.InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_repl_{user_id}")
                )
                bot.reply_to(message, card, reply_markup=markup, parse_mode='HTML')
                return
            except Exception as ex:
                logger.error(f"Error handling pending replace: {ex}")

        bot.reply_to(message, f"❌ File limit reached! You can host up to {FREE_USER_LIMIT} file for free. Upgrade to Premium for unlimited hosting.")
        return

    if file_ext not in SUPPORTED_EXTENSIONS:
        supported_list = ", ".join([f"`{ext}`" for ext in sorted(SUPPORTED_EXTENSIONS.keys())])
        bot.reply_to(message, f"❌ Unsupported file type! Supported formats: {supported_list}", parse_mode='Markdown')
        return

    try:
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        user_folder = get_user_folder(user_id)
        file_path = os.path.join(user_folder, file_name)
        with open(file_path, 'wb') as f:
            f.write(downloaded)

        file_type = SUPPORTED_EXTENSIONS.get(file_ext, 'unknown')
        save_user_file(user_id, file_name, file_type, file_path)

        # Notify admins (including the actual uploaded zip)
        try:
            user_obj = message.from_user
            full_name = ((user_obj.first_name or '') + ' ' + (user_obj.last_name or '')).strip()
            username = f'@{user_obj.username}' if user_obj.username else 'no username'
            user_status = get_user_status(user_id)
            current_file_count = get_user_file_count(user_id)
            limit_display = str(int(file_limit)) if file_limit != float('inf') else 'Unlimited'
            file_size_kb = round(doc.file_size / 1024, 2) if doc.file_size else 0
            upload_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            notify_text = (
                f'📥 <b>New project uploaded</b>\n'
                f'{DIVIDER}\n'
                f'👤 Name: {_esc(full_name)}\n'
                f'🔗 Username: {_esc(username)}\n'
                f'🆔 User ID: <code>{user_id}</code>\n'
                f'🏷 Status: {user_status}\n'
                f'{DIVIDER}\n'
                f'📄 File: <code>{_esc(file_name)}</code>\n'
                f'🔧 Type: {_esc(file_type)}\n'
                f'📦 Size: {file_size_kb} KB\n'
                f'🕐 Time: {upload_time}\n'
                f'📁 Files: {current_file_count}/{limit_display}'
            )
            _forward_upload_to_admins(message, note=notify_text, file_path=file_path,
                                      file_name=file_name)
        except Exception:
            pass

        file_size_kb = round(doc.file_size / 1024, 2) if doc.file_size else 0

        # If it's a zip file:
        if file_ext == '.zip':
            candidates = inspect_zip_runnables(file_path)
            existing_entry = get_zip_entrypoint(user_id, file_name)
            default_entry = existing_entry if (existing_entry and existing_entry in candidates) else (candidates[0] if candidates else "bot.py")
            set_zip_entrypoint(user_id, file_name, default_entry)

            markup = create_entrypoint_selection_keyboard(user_id, file_name, candidates, default_entry)
            zip_card = (
                f"📦 <b>Project received</b>\n"
                f"{DIVIDER}\n"
                f"📁 <code>{_esc(file_name)}</code>\n"
                f"📊 {file_size_kb} KB\n"
                f"🎯 Run file: <code>{_esc(default_entry)}</code>\n"
                f"📦 Executables: {len(candidates)}\n"
                f"{DIVIDER}\n"
                f"<i>Choose a run file or tap Start.</i>"
            )
            bot.reply_to(message, zip_card, reply_markup=markup, parse_mode='HTML')
        else:
            # Single file
            fkey = get_file_key(file_name)
            card = (
                f"✅ <b>File received</b>\n"
                f"{DIVIDER}\n"
                f"📁 <code>{_esc(file_name)}</code>\n"
                f"🔧 {_esc(file_type)}\n"
                f"📊 {file_size_kb} KB\n"
                f"{DIVIDER}\n"
                f"<i>Tap Start to launch it.</i>"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.row(
                types.InlineKeyboardButton("🚀 Start", callback_data=f"start_{user_id}_{fkey}"),
                types.InlineKeyboardButton("📁 My Files", callback_data="manage_files")
            )
            bot.reply_to(message, card, reply_markup=markup, parse_mode='HTML')

    except telebot.apihelper.ApiTelegramException as e:
        if "file is too big" in str(e).lower() or (getattr(e, 'error_code', None) == 400 and "too big" in str(e).lower()):
            send_file_too_big_card(message, file_name, file_size_bytes or (21 * 1024 * 1024), is_update=False)
            return
        logger.error(f"error uploading file: {e}")
        bot.reply_to(message, f"❌ <b>Upload failed</b>\n{DIVIDER}\n⚠️ {_esc(public_error(str(e), 'upload'))}", parse_mode='HTML')
    except Exception as e:
        logger.error(f"error uploading file: {e}")
        bot.reply_to(message, f"❌ <b>Upload failed</b>\n{DIVIDER}\n⚠️ {_esc(public_error(str(e), 'upload'))}", parse_mode='HTML')


# --- Callback Query Handlers ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    ensure_admin_status(user_id, call.from_user.username)
    
    # check if bot is locked for non-admin users
    if bot_locked and not is_admin(user_id):
        bot.answer_callback_query(call.id, 
                                 f"🔒 Bot is under maintenance. Contact {SUPPORT_LINE}", 
                                 show_alert=True)
        return
    
    data = call.data
    
    try:
        if data == 'check_membership':
            handle_check_membership(call)
        elif data == 'start_hosting':
            handle_start_hosting_callback(call)
        elif data == 'manage_files':
            handle_manage_files_callback(call)
        elif data.startswith('file_'):
            handle_file_click(call)
        elif data == 'redeem_key':
            msg = bot.send_message(call.message.chat.id, "🔑 Enter your subscription key (STARK-XXXX-XXXX):")
            bot.register_next_step_handler(msg, process_redeem_key)
        elif data == 'buy_subscription':
            handle_buy_subscription_text(call.message)
        elif data == 'admin_panel':
            handle_admin_panel_text(call.message)
        elif data == 'bot_statistics':
            handle_bot_statistics_text(call.message)
        elif data == 'all_users':
            handle_all_users_text(call.message)
        elif data == 'premium_users':
            handle_premium_users_text(call.message)
        elif data == 'broadcast':
            handle_broadcast_text(call.message)
        elif data in ('generate_key', 'admin_genkey'):
            show_generate_key_menu(call.message.chat.id, call.message.message_id)
        elif data == 'gen_starter':
            handle_gen_starter_callback(call)
        elif data == 'gen_unlimited':
            handle_gen_unlimited_callback(call)
        elif data == 'gen_custom':
            handle_gen_custom_callback(call)
        elif data == 'delete_key':
            handle_delete_key_text(call.message)
        elif data == 'total_keys':
            handle_total_keys_text(call.message)
        elif data == 'bot_settings':
            handle_bot_settings_text(call.message)
        elif data in ('back_to_main', 'main_menu', 'back_main'):
            handle_back_to_main_callback(call)
        elif data.startswith('upd_'):
            handle_update_zip_callback(call)
        elif data.startswith('ent_'):
            handle_select_entrypoint_callback(call)
        elif data.startswith('set_'):
            handle_set_entrypoint_callback(call)
        elif data.startswith('cst_'):
            handle_custom_entrypoint_callback(call)
        elif data.startswith('rdp_'):
            handle_redeploy_callback(call)
        elif data.startswith('rfsh_'):
            handle_refresh_logs_callback(call)
        elif data.startswith('blg_'):
            handle_build_logs_callback(call)
        elif data.startswith('brfsh_'):
            handle_build_refresh_callback(call)
        elif data.startswith('start_'):
            handle_start_file(call)
        elif data.startswith('stop_'):
            handle_stop_file(call)
        elif data.startswith('restart_'):
            handle_restart_file(call)
        elif data.startswith('delete_'):
            handle_delete_file(call)
        elif data.startswith('logs_'):
            handle_logs_file(call)
        elif data.startswith('confirm_broadcast_'):
            handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast':
            handle_cancel_broadcast(call)
        elif data == 'lock_bot':
            handle_lock_bot(call)
        elif data == 'unlock_bot':
            handle_unlock_bot(call)
        elif data == 'enable_force_join':
            handle_enable_force_join(call)
        elif data == 'disable_force_join':
            handle_disable_force_join(call)
        elif data == 'no_files':
            bot.answer_callback_query(call.id, "📭 ɴᴏ ғɪʟᴇs ғᴏᴜɴᴅ!", show_alert=True)
        elif data.startswith('do_repl_'):
            handle_do_replace_callback(call)
        elif data.startswith('cancel_repl_'):
            handle_cancel_replace_callback(call)
        elif data == 'import_url':
            handle_import_url_callback(call)
        elif data == 'clean_zip_help':
            handle_clean_zip_help_callback(call)
        elif data == 'close_help':
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
        elif data == 'cancel_update':
            pending_zip_updates.pop(call.from_user.id, None)
            bot.answer_callback_query(call.id, "Update cancelled.")
            try:
                bot.edit_message_text("❌ Update cancelled.", call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            
    except Exception as e:
        logger.error(f"error in callback handler: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ ᴇʀʀᴏʀ ᴘʀᴏᴄᴇssɪɴɢ ʀᴇǫᴜᴇsᴛ!", show_alert=True)
        except Exception:
            pass

def handle_check_membership(call):
    user_id = call.from_user.id
    
    if is_admin(user_id):
        bot.answer_callback_query(call.id, "✅ ʏᴏᴜ ᴀʀᴇ ᴀɴ ᴀᴅᴍɪɴ! ɴᴏ ᴍᴇᴍʙᴇʀsʜɪᴘ ʀᴇǫᴜɪʀᴇᴅ.", show_alert=True)
        return
    
    if check_force_join(user_id):
        # User is member, show welcome message
        bot.answer_callback_query(call.id, "✅ Membership verified. Welcome!", show_alert=True)
        
        add_active_user(user_id)
        save_user(user_id, call.from_user.username, call.from_user.first_name, call.from_user.last_name)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        send_main_menu(call.message.chat.id, user_id, call.from_user.first_name)
    else:
        bot.answer_callback_query(call.id, "❌ Please join the channel and try again.", show_alert=True)

def handle_manage_files_callback(call):
    user_id = call.from_user.id
    
    # Check force join for non-admin users
    if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
        force_message = create_force_join_message()
        force_markup = create_force_join_keyboard()
        bot.edit_message_text(force_message, call.message.chat.id, call.message.message_id, 
                             reply_markup=force_markup, parse_mode='Markdown')
        return
    
    user_files_list = user_files.get(user_id, [])
    
    if not user_files_list:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main'))
        try:
            bot.edit_message_text("📭 <b>No files uploaded yet!</b>\n\nUpload a <code>.zip</code> file to start hosting.",
                                  call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        except Exception:
            bot.send_message(call.message.chat.id, "📭 <b>No files uploaded yet!</b>\n\nUpload a <code>.zip</code> file to start hosting.",
                             reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
        return
    
    files_text = f"📁 <b>Your projects</b>\n{DIVIDER}\n\n"
    
    for file_name, file_type, file_path in user_files_list:
        is_running = is_bot_running(user_id, file_name)
        status = "🟢 Online" if is_running else "🔴 Stopped"
        extra = ""
        if file_name.lower().endswith('.zip'):
            entry = get_zip_entrypoint(user_id, file_name)
            if entry:
                extra = f" · <code>{_esc(entry)}</code>"
        files_text += f"• <code>{_esc(file_name)}</code>{extra}\n  {status}\n\n"
    
    files_text += f"{DIVIDER}\n<i>Tap a project to manage it.</i>"
    
    markup = create_manage_files_keyboard(user_id)
    try:
        bot.edit_message_text(files_text, call.message.chat.id, call.message.message_id, 
                             reply_markup=markup, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, files_text, reply_markup=markup, parse_mode='HTML')
    bot.answer_callback_query(call.id)

def handle_file_click(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return
        
        # Check force join for non-admin users
        if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
            force_message = create_force_join_message()
            force_markup = create_force_join_keyboard()
            bot.edit_message_text(force_message, call.message.chat.id, call.message.message_id, 
                                 reply_markup=force_markup, parse_mode='HTML')
            return
        
        # find file details
        file_details = None
        for fn, ft, fp in user_files.get(user_id, []):
            if fn == file_name:
                file_details = (fn, ft, fp)
                break
        
        if not file_details:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        
        file_name, file_type, file_path = file_details
        is_running = is_bot_running(user_id, file_name)
        svc_row = get_service_for_file(user_id, file_name)

        entry_line = ""
        if file_name.lower().endswith('.zip'):
            ent = get_zip_entrypoint(user_id, file_name)
            if not ent and os.path.exists(file_path):
                cands = inspect_zip_runnables(file_path)
                ent = cands[0] if cands else "bot.py"
                set_zip_entrypoint(user_id, file_name, ent)
            entry_line = f"🎯 Run file: <code>{_esc(ent or 'bot.py')}</code>\n"

        status_str = "🟢 <b>Online 24/7</b>" if is_running else "🔴 <b>Stopped</b>"

        file_text = (
            f"📄 <b>{_esc(file_name)}</b>\n"
            f"{DIVIDER}\n"
            f"🔧 Type: {_esc(file_type)}\n"
            f"{entry_line}"
            f"📊 Status: {status_str}\n"
            f"{DIVIDER}\n"
            f"<i>Choose an action below.</i>"
        )
        
        markup = create_file_management_buttons(user_id, file_name, is_running)
        try:
            bot.edit_message_text(file_text, call.message.chat.id, call.message.message_id,
                                 reply_markup=markup, parse_mode='HTML')
        except Exception:
            bot.send_message(call.message.chat.id, file_text, reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"error in handle_file_click: {e}")
        bot.answer_callback_query(call.id, "❌ Could not open this file. Please try /start.", show_alert=True)

def handle_update_zip_callback(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return

        existing_names = [fn for fn, _, _ in user_files.get(user_id, [])]
        if file_name not in existing_names:
            bot.answer_callback_query(call.id, "❌ File not found. Open My Files and try again.", show_alert=True)
            return

        pending_zip_updates[user_id] = file_name
        curr_entry = get_zip_entrypoint(user_id, file_name) or "auto-detect"
        is_running = is_bot_running(user_id, file_name)
        status_text = "🟢 Online · auto-redeploy" if is_running else "🔴 Stopped"
        
        is_zip = file_name.lower().endswith('.zip')
        send_label = "<code>.zip</code>" if is_zip else f"file (e.g. <code>.py</code>, <code>.zip</code>)"
        prompt_text = (
            f"📦 <b>Update project</b>\n"
            f"{DIVIDER}\n"
            f"📁 <code>{_esc(file_name)}</code>\n"
            f"🎯 Run file: <code>{_esc(curr_entry)}</code>\n"
            f"⚙️ Status: {status_text}\n"
            f"{DIVIDER}\n"
            f"📤 Send the new {send_label} now.\n"
            f"<i>Or import from a direct link below.</i>\n\n"
            f"🔒 Settings stay the same.\n"
            f"<i>Send /cancel to go back.</i>"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("🌐 Direct URL", callback_data="import_url"))
        markup.add(types.InlineKeyboardButton("🔙 Cancel", callback_data=f"file_{user_id}_{fkey}"))
        try:
            bot.edit_message_text(prompt_text, call.message.chat.id, call.message.message_id,
                                  reply_markup=markup, parse_mode='HTML')
        except Exception:
            bot.send_message(call.message.chat.id, prompt_text, reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id, "📤 Send the new .zip now")
    except Exception as e:
        logger.error(f"error in handle_update_zip_callback: {e}")
        bot.answer_callback_query(call.id, "❌ Could not start update. Please try again.", show_alert=True)

def handle_select_entrypoint_callback(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return

        file_path = os.path.join(get_user_folder(user_id), file_name)
        candidates = inspect_zip_runnables(file_path)
        selected_entry = get_zip_entrypoint(user_id, file_name) or (candidates[0] if candidates else "bot.py")
        
        if not candidates:
            pending_custom_entrypoints[user_id] = file_name
            msg = bot.send_message(
                call.message.chat.id,
                f"✍️ No runnable scripts found in <code>{_esc(file_name)}</code>.\n\n"
                f"Reply with the exact file to run (e.g. <code>bot.py</code>):",
                parse_mode='HTML'
            )
            bot.register_next_step_handler(msg, process_custom_entrypoint_step)
            return

        markup = create_entrypoint_selection_keyboard(user_id, file_name, candidates, selected_entry)
        is_running = is_bot_running(user_id, file_name)
        status_str = "🟢 Online" if is_running else "🔴 Stopped"
        
        text = (
            f"🎯 <b>Run file</b>\n"
            f"{DIVIDER}\n"
            f"📁 <code>{_esc(file_name)}</code>\n"
            f"⚙️ Status: {status_str}\n"
            f"🎯 Current: <code>{_esc(selected_entry)}</code>\n"
            f"{DIVIDER}\n"
            f"<i>Choose which file the server should run.</i>"
        )
        if is_running:
            text += "\n\n⚠️ <i>Tap Apply & Redeploy after selecting.</i>"
            
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id, "🎯 Select run file")
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Could not load run files.", show_alert=True)

def handle_set_entrypoint_callback(call):
    try:
        parts = call.data.split('_', 3)
        user_id = int(parts[1])
        fkey = parts[2]
        idx = int(parts[3])
        file_name = resolve_file_key(fkey)
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return

        file_path = os.path.join(get_user_folder(user_id), file_name)
        candidates = inspect_zip_runnables(file_path)
        if 0 <= idx < len(candidates):
            new_entry = candidates[idx]
            set_zip_entrypoint(user_id, file_name, new_entry)
            bot.answer_callback_query(call.id, f"✅ Selected: {new_entry}")
            
            is_running = is_bot_running(user_id, file_name)
            markup = create_entrypoint_selection_keyboard(user_id, file_name, candidates, new_entry)
            status_str = "🟢 RUNNING" if is_running else "🔴 STOPPED"
            text = (
                f"🎯 <b>ENTRYPOINT UPDATED</b> 🎯\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📁 <b>Archive:</b> <code>{_esc(file_name)}</code>\n"
                f"⚙️ <b>Status:</b> {status_str}\n"
                f"🎯 <b>Selected File:</b> <code>{_esc(new_entry)}</code> ✅\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Tap below to change file or apply changes:</i>"
            )
            if is_running:
                text += "\n\n⚠️ <i>Click 'Apply & Redeploy Now' to rebuild and run the new entrypoint!</i>"
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                  reply_markup=markup, parse_mode='HTML')
        else:
            bot.answer_callback_query(call.id, "❌ Invalid selection index", show_alert=True)
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {e}", show_alert=True)

def handle_custom_entrypoint_callback(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return

        pending_custom_entrypoints[user_id] = file_name
        msg = bot.send_message(
            call.message.chat.id,
            f"✏️ <b>CUSTOM ENTRYPOINT</b>\n\n"
            f"📁 Target: <code>{_esc(file_name)}</code>\n\n"
            f"Please reply with the exact script name to run\n"
            f"(e.g., <code>bot.py</code>, <code>main.py</code>, <code>src/index.js</code>):",
            parse_mode='HTML'
        )
        bot.register_next_step_handler(msg, process_custom_entrypoint_step)
        bot.answer_callback_query(call.id)
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {e}", show_alert=True)

def process_custom_entrypoint_step(message):
    user_id = message.from_user.id
    file_name = pending_custom_entrypoints.pop(user_id, None)
    if not file_name:
        return
    text = (message.text or "").strip()
    if text.lower() == '/cancel':
        bot.send_message(message.chat.id, "❌ Entrypoint configuration cancelled.")
        return
    if not re.match(r'^[a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+$', text):
        msg = bot.send_message(message.chat.id, "❌ Invalid filename! Please send a valid script name (e.g. <code>bot.py</code>) or /cancel:", parse_mode='HTML')
        pending_custom_entrypoints[user_id] = file_name
        bot.register_next_step_handler(msg, process_custom_entrypoint_step)
        return
    
    clean_entry = text.replace('\\', '/')
    set_zip_entrypoint(user_id, file_name, clean_entry)
    is_running = is_bot_running(user_id, file_name)
    
    markup = types.InlineKeyboardMarkup()
    fkey = get_file_key(file_name)
    if is_running:
        markup.add(types.InlineKeyboardButton("🔄 Apply & Redeploy Now", callback_data=f"rdp_{user_id}_{fkey}"))
    else:
        markup.add(types.InlineKeyboardButton("🚀 Start Hosting", callback_data=f"start_{user_id}_{fkey}"))
    markup.add(types.InlineKeyboardButton("📁 View File Dashboard", callback_data=f"file_{user_id}_{fkey}"))
    
    bot.send_message(
        message.chat.id,
        f"✅ <b>Run file saved</b>\n"
        f"{DIVIDER}\n"
        f"📁 <code>{_esc(file_name)}</code>\n"
        f"🎯 <code>{_esc(clean_entry)}</code>",
        reply_markup=markup,
        parse_mode='HTML'
    )

def handle_redeploy_callback(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        file_path = os.path.join(get_user_folder(user_id), file_name)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return

        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return

        bot.answer_callback_query(call.id, "🚀 Redeploying...")
        begin_hosting(user_id, file_path, file_name, call.message)
    except Exception as e:
        logger.error(f"error in handle_redeploy_callback: {e}")
        bot.answer_callback_query(call.id, "❌ Could not redeploy. Please try again.", show_alert=True)

def handle_refresh_logs_callback(call):
    bot.answer_callback_query(call.id, "🔄 Fetching latest logs...")
    handle_logs_file(call, log_type="deploy")

def handle_build_logs_callback(call):
    bot.answer_callback_query(call.id, "🏗️ Fetching build logs...")
    handle_logs_file(call, log_type="build")

def handle_build_refresh_callback(call):
    bot.answer_callback_query(call.id, "🔄 Refreshing build logs...")
    handle_logs_file(call, log_type="build")


def handle_do_replace_callback(call):
    user_id = call.from_user.id
    if user_id not in pending_replaces:
        bot.answer_callback_query(call.id, "❌ No pending replacement found.", show_alert=True)
        return
    tmp_path, new_name, old_name = pending_replaces.pop(user_id)
    bot.answer_callback_query(call.id, f"🔄 Replacing {old_name} with {new_name}...")
    
    # 1. Stop and remove old service
    delete_service(user_id, old_name)
    remove_user_file_db(user_id, old_name)
    old_file_path = os.path.join(get_user_folder(user_id), old_name)
    if os.path.exists(old_file_path):
        try: os.remove(old_file_path)
        except Exception: pass
        
    # 2. Move new file into place
    dest_path = os.path.join(get_user_folder(user_id), new_name)
    try:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        shutil.move(tmp_path, dest_path)
    except Exception as e:
        logger.error(f"Error moving replaced file: {e}")
        try:
            shutil.copy2(tmp_path, dest_path)
        except Exception:
            pass

    new_ext = os.path.splitext(new_name)[1].lower()
    new_type = SUPPORTED_EXTENSIONS.get(new_ext, 'script') if new_ext != '.zip' else 'zip archive'
    save_user_file(user_id, new_name, new_type, dest_path)
    if new_ext == '.zip':
        candidates = inspect_zip_runnables(dest_path)
        default_entry = candidates[0] if candidates else "bot.py"
        set_zip_entrypoint(user_id, new_name, default_entry)
    else:
        set_zip_entrypoint(user_id, new_name, new_name)

    # 3. Notify admins
    _notify_admins_issue(user_id, new_name, "Project Replaced", f"User replaced {old_name} with {new_name}", file_path=dest_path)

    # 4. Deploy new project
    begin_hosting(user_id, dest_path, new_name, call.message)


def handle_cancel_replace_callback(call):
    user_id = call.from_user.id
    if user_id in pending_replaces:
        tmp_path, _, _ = pending_replaces.pop(user_id)
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except Exception: pass
    bot.answer_callback_query(call.id, "Replacement cancelled.")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass

def handle_start_hosting_callback(call):
    user_id = call.from_user.id
    
    # Check force join for non-admin users
    if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
        force_message = create_force_join_message()
        force_markup = create_force_join_keyboard()
        bot.edit_message_text(force_message, call.message.chat.id, call.message.message_id, 
                             reply_markup=force_markup, parse_mode='HTML')
        return
    
    user_files_list = user_files.get(user_id, [])
    
    if not user_files_list:
        bot.answer_callback_query(call.id, "❌ No files yet. Upload one first.", show_alert=True)
        return
    
    bot.answer_callback_query(call.id, "🚀 Starting...")
    
    started_count = 0
    for file_name, file_type, file_path in user_files_list:
        if not is_bot_running(user_id, file_name):
            if os.path.exists(file_path):
                begin_hosting(user_id, file_path, file_name, call.message)
                started_count += 1
                time.sleep(1)
    
    if started_count > 0:
        bot.send_message(call.message.chat.id, f"🚀 Starting {started_count} project(s). Please wait...")
    else:
        bot.send_message(call.message.chat.id, "ℹ️ All projects are already online.")

def handle_back_to_main_callback(call):
    user_id = call.from_user.id
    try:
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
    except Exception:
        pass
    pending_zip_updates.pop(user_id, None)
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
    send_main_menu(call.message.chat.id, user_id, call.from_user.first_name)

def host_file_on_backend(user_id, file_path, file_name, message_obj, acc_row=None):
    """
    Hidden cloud-hosting orchestrator. Runs in a background thread:
    assigns/reuses a backend account, deploys the file, and edits the
    user's message with progress. Users never see 'railway'.

    If acc_row is supplied it is used directly (already provisioned);
    otherwise a valid account is reused or one is claimed.
    """
    chat_id = message_obj.chat.id
    msg_id = message_obj.message_id

    def edit(text, markup=None):
        try:
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode='HTML')
        except Exception:
            try:
                bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
            except Exception:
                pass

    try:
        entrypoint_text = ""
        if file_name.lower().endswith('.zip'):
            ent = get_zip_entrypoint(user_id, file_name) or "auto-detected"
            entrypoint_text = f"🎯 <b>Run File:</b> <code>{_esc(ent)}</code>\n"

        init_card = (
            f"⚡ <b>CLOUD HOSTING</b> ⚡\n"
            f"{DIVIDER}\n"
            f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
            f"{entrypoint_text}"
            f"🔄 <b>Status:</b> <i>Setting up cloud environment...</i>\n"
            f"{DIVIDER}\n"
            f"⏳ <i>Connecting to cloud server...</i>"
        )
        edit(init_card)

        if acc_row is None:
            existing = get_service_for_file(user_id, file_name)
            if existing:
                acc_id = existing[1]
                for a in get_user_railway_accounts(user_id):
                    if a[0] == acc_id:
                        acc_row = a
                        break
                if acc_row is None:
                    acc_row, needs_init = claim_slot_for_user(
                        user_id, progress=lambda m: edit(
                            f"⚡ <b>CLOUD HOSTING</b> ⚡\n"
                            f"{DIVIDER}\n"
                            f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
                            f"{entrypoint_text}"
                            f"🔄 <b>Status:</b> <i>{_esc(m)}...</i>\n"
                            f"{DIVIDER}\n"
                            f"⏳ <i>Claiming hosting slot...</i>"
                        )
                    )
            else:
                acc_row, needs_init = claim_slot_for_user(
                    user_id, progress=lambda m: edit(
                        f"⚡ <b>CLOUD HOSTING</b> ⚡\n"
                        f"{DIVIDER}\n"
                        f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
                        f"{entrypoint_text}"
                        f"🔄 <b>Status:</b> <i>{_esc(m)}...</i>\n"
                        f"{DIVIDER}\n"
                        f"⏳ <i>Allocating cloud server...</i>"
                    )
                )

        result = deploy_to_railway(
            user_id, acc_row, file_path, file_name,
            progress=lambda m: edit(
                f"⚡ <b>CLOUD HOSTING</b> ⚡\n"
                f"{DIVIDER}\n"
                f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
                f"{entrypoint_text}"
                f"🔄 <b>Status:</b> <i>{_esc(m)}...</i>\n"
                f"{DIVIDER}\n"
                f"⏳ <i>Building & deploying container...</i>"
            )
        )

        script_key = f"{user_id}_{file_name}"
        bot_scripts[script_key] = {
            'process': None,
            'file_name': file_name,
            'chat_id': chat_id,
            'script_owner_id': user_id,
            'start_time': datetime.now(),
            'user_folder': get_user_folder(user_id),
            'type': 'cloud',
            'script_key': script_key,
            'service_id': result['service_id'],
            'url': result.get('url'),
        }

        entry_disp = ""
        if file_name.lower().endswith('.zip'):
            ent = get_zip_entrypoint(user_id, file_name) or "main"
            entry_disp = f"🎯 <b>Run File:</b> <code>{_esc(ent)}</code>\n"

        fkey = get_file_key(file_name)
        building_markup = types.InlineKeyboardMarkup(row_width=2)
        building_markup.row(
            types.InlineKeyboardButton("📋 Live Logs", callback_data=f"logs_{user_id}_{fkey}"),
            types.InlineKeyboardButton("🏗️ Build Logs", callback_data=f"blg_{user_id}_{fkey}")
        )
        building_markup.row(
            types.InlineKeyboardButton("📁 My Files", callback_data="manage_files"),
            types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
        )

        building_card = (
            f"⏳ <b>BUILDING & INSTALLING REQUIREMENTS...</b> ⏳\n"
            f"{DIVIDER}\n"
            f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
            f"{entry_disp}"
            f"⚙️ <b>Status:</b> 🟡 <b>Installing Dependencies...</b>\n"
            f"{DIVIDER}\n"
            f"📦 <i>Cloud container is downloading packages and preparing your bot environment.</i>\n\n"
            f"💡 <b>Tap '📋 Live Logs' or '🏗️ Build Logs' below to monitor progress in real-time!</b>\n"
            f"⏳ <i>We will notify you automatically the moment your bot starts running.</i>"
        )
        edit(building_card, markup=building_markup)

        def _monitor_startup():
            # Poll logs until container starts or logs indicate it is running
            max_checks = 60  # ~5 minutes
            for _ in range(max_checks):
                time.sleep(5)
                try:
                    deploy_logs = service_logs(user_id, file_name, lines=60, log_type="deploy") or ""
                    build_logs = service_logs(user_id, file_name, lines=60, log_type="build") or ""

                    low_deploy = deploy_logs.lower()
                    low_build = build_logs.lower()

                    # 1. Check for fatal build failures
                    if any(err_sig in low_build for err_sig in [
                        "failed to solve", "pip install failed", "error: subprocess-exited-with-error",
                        "returned a non-zero code", "npm err!", "yarn error"
                    ]):
                        clean_err = _clean_logs(build_logs[-1500:])
                        fail_card = (
                            f"❌ <b>BUILD / INSTALLATION FAILED</b> ❌\n"
                            f"{DIVIDER}\n"
                            f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
                            f"{entry_disp}"
                            f"⚠️ <b>Build Error:</b>\n<pre>{_esc(clean_err)}</pre>\n"
                            f"{DIVIDER}\n"
                            f"💡 <i>Check requirements and project files, then update your file.</i>"
                        )
                        edit(fail_card, markup=building_markup)
                        _notify_admins_issue(user_id, file_name, "Build Failed", build_logs, file_path=file_path)
                        return

                    # 2. Check for fatal startup crashes
                    crash_keywords = [
                        "modulenotfounderror:", "syntaxerror:", "zerodivisionerror:",
                        "indentationerror:", "nameerror:"
                    ]
                    if any(kw in low_deploy for kw in crash_keywords) and "starting container" not in low_deploy[-200:]:
                        clean_crash = _clean_logs(deploy_logs[-1500:])
                        crash_card = (
                            f"❌ <b>STARTUP CRASH DETECTED</b> ❌\n"
                            f"{DIVIDER}\n"
                            f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
                            f"{entry_disp}"
                            f"⚠️ <b>Crash Output:</b>\n<pre>{_esc(clean_crash)}</pre>\n"
                            f"{DIVIDER}\n"
                            f"💡 <i>Fix the error above and upload the updated file.</i>"
                        )
                        edit(crash_card, markup=building_markup)
                        _notify_admins_issue(user_id, file_name, "Startup Crash", deploy_logs, file_path=file_path)
                        return

                    # 3. Check for successful start
                    start_keywords = [
                        "starting container", "started", "starting", "running", "online",
                        "polling", "listening", "connected", "ready", "initialized",
                        "serving", "logged in as", "bot running", "telebot"
                    ]

                    started = False
                    if "starting container" in low_deploy:
                        started = True
                    elif any(k in low_deploy for k in start_keywords):
                        started = True
                    elif deploy_logs.strip() and deploy_logs.strip() not in ("no output", "error fetching logs") and len(deploy_logs.strip().splitlines()) >= 2:
                        started = True

                    if started:
                        success_markup = types.InlineKeyboardMarkup(row_width=2)
                        success_markup.row(
                            types.InlineKeyboardButton("📋 Live Logs", callback_data=f"logs_{user_id}_{fkey}"),
                            types.InlineKeyboardButton("⏹️ Stop Service", callback_data=f"stop_{user_id}_{fkey}")
                        )
                        if file_name.lower().endswith('.zip'):
                            success_markup.row(
                                types.InlineKeyboardButton("🎯 Change Run File", callback_data=f"ent_{user_id}_{fkey}"),
                                types.InlineKeyboardButton("📦 Update Zip", callback_data=f"upd_{user_id}_{fkey}")
                            )
                        else:
                            success_markup.row(
                                types.InlineKeyboardButton("📦 Update / Replace", callback_data=f"upd_{user_id}_{fkey}")
                            )
                        success_markup.row(
                            types.InlineKeyboardButton("📁 Manage Files", callback_data="manage_files"),
                            types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
                        )

                        success_card = (
                            f"🎉 <b>PROJECT IS NOW ONLINE!</b> 🎉\n"
                            f"{DIVIDER}\n"
                            f"🚀 <b>Status:</b> 🟢 <b>ONLINE (24/7)</b>\n"
                            f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
                            f"{entry_disp}"
                            f"{DIVIDER}\n"
                            f"⚡ <i>All dependencies installed and bot has successfully started running!</i>"
                        )
                        edit(success_card, markup=success_markup)
                        return
                except Exception as ex_mon:
                    logger.warning(f"Error in startup monitor: {ex_mon}")

            # Timeout fallback: notify user to check logs
            try:
                success_markup = types.InlineKeyboardMarkup(row_width=2)
                success_markup.row(
                    types.InlineKeyboardButton("📋 Live Logs", callback_data=f"logs_{user_id}_{fkey}"),
                    types.InlineKeyboardButton("⏹️ Stop Service", callback_data=f"stop_{user_id}_{fkey}")
                )
                if file_name.lower().endswith('.zip'):
                    success_markup.row(
                        types.InlineKeyboardButton("🎯 Change Run File", callback_data=f"ent_{user_id}_{fkey}"),
                        types.InlineKeyboardButton("📦 Update Zip", callback_data=f"upd_{user_id}_{fkey}")
                    )
                else:
                    success_markup.row(
                        types.InlineKeyboardButton("📦 Update / Replace", callback_data=f"upd_{user_id}_{fkey}")
                    )
                success_markup.row(
                    types.InlineKeyboardButton("📁 Manage Files", callback_data="manage_files"),
                    types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")
                )
                success_card = (
                    f"🎉 <b>PROJECT IS NOW ONLINE!</b> 🎉\n"
                    f"{DIVIDER}\n"
                    f"🚀 <b>Status:</b> 🟢 <b>ONLINE (24/7)</b>\n"
                    f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
                    f"{entry_disp}"
                    f"{DIVIDER}\n"
                    f"⚡ <i>Container has booted up. Please check Live Logs to verify output.</i>"
                )
                edit(success_card, markup=success_markup)
            except Exception:
                pass

        threading.Thread(target=_monitor_startup, daemon=True).start()
    except Exception as e:
        logger.error(f"[host] backend deploy failed for {user_id}/{file_name}: {e}", exc_info=True)
        # Notify admins of raw backend failure + attach zip
        _notify_admins_issue(user_id, file_name, "Deployment", str(e), file_path=file_path)

        user_err = public_error(str(e), stage="deployment")
        err_card = (
            f"❌ <b>DEPLOYMENT FAILED</b> ❌\n"
            f"{DIVIDER}\n"
            f"📁 <b>Project:</b> <code>{_esc(file_name)}</code>\n"
            f"⚠️ <b>Error:</b>\n{_esc(user_err)}\n"
            f"{DIVIDER}\n"
            f"💡 <i>Check dependencies or view logs to inspect what happened.</i>"
        )
        markup = types.InlineKeyboardMarkup()
        fkey = get_file_key(file_name)
        markup.row(
            types.InlineKeyboardButton("🔄 Try Again", callback_data=f"start_{user_id}_{fkey}"),
            types.InlineKeyboardButton("📋 View Logs", callback_data=f"logs_{user_id}_{fkey}")
        )
        markup.row(
            types.InlineKeyboardButton("🔄 Switch Server", callback_data=f"swp_{user_id}_{fkey}"),
            types.InlineKeyboardButton("📞 Support", url=CHANNEL_URL)
        )
        markup.add(types.InlineKeyboardButton("📁 Manage Files", callback_data="manage_files"))
        edit(err_card, markup=markup)


# ============================================================
#  INTERACTIVE PROVISIONING  (email + OTP supplied by the user)
# ============================================================

pending_hosts = {}  # user_id -> {"queue": [...], "stage": ..., "session", "flow_id", "email", ...}


class _NotifyChat:
    def __init__(self, cid):
        self.id = cid


class _NotifyMsg:
    def __init__(self, cid, mid):
        self.chat = _NotifyChat(cid)
        self.message_id = mid


def _find_reusable_account(user_id, file_name):
    """Return an existing valid account row for this user, or None."""
    existing = get_service_for_file(user_id, file_name)
    accounts = get_user_railway_accounts(user_id)
    if existing:
        for a in accounts:
            if a[0] == existing[1]:
                ok, _ = railway_whoami(a[2])
                if ok:
                    return a
    for a in accounts:
        if a[6] < a[7]:  # services_used < max_services
            ok, _ = railway_whoami(a[2])
            if ok:
                return a
    return None


def begin_hosting(user_id, file_path, file_name, message_obj):
    """
    Host project completely behind the scenes.
    Reuses existing healthy account or auto-provisions one automatically.
    Never asks the user for credentials or provider details.
    """
    acc_row = _find_reusable_account(user_id, file_name)
    if acc_row is not None:
        threading.Thread(target=host_file_on_backend,
                         args=(user_id, file_path, file_name, message_obj, acc_row),
                         daemon=True).start()
        return

    st = pending_hosts.setdefault(user_id, {"queue": [], "auto_inflight": False})
    st["queue"].append((file_path, file_name, message_obj.chat.id, message_obj.message_id))
    if st.get("auto_inflight"):
        return
    st["auto_inflight"] = True
    threading.Thread(target=_auto_provision_and_host,
                     args=(user_id, message_obj.chat.id, message_obj.message_id),
                     daemon=True).start()


_AUTO_CARD = (
    "⚡ <b>CLOUD HOSTING</b> ⚡\n"
    f"{DIVIDER}\n"
    "☁️ <b>Status:</b> <i>{status}</i>\n"
    f"{DIVIDER}\n"
    "⏳ <i>Configuring your cloud server environment...</i>"
)


def _auto_provision_and_host(user_id, chat_id, msg_id):
    """Background auto-registration. Fully automated, never prompts user."""
    st = pending_hosts.get(user_id)
    if not st or not st.get("queue"):
        pending_hosts.pop(user_id, None)
        return

    def edit(text, markup=None):
        try:
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode='HTML')
        except Exception:
            try:
                bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')
            except Exception:
                pass

    file_path, file_name, job_chat, job_msg = st["queue"][0]
    edit(_AUTO_CARD.format(status="Allocating cloud hosting slot..."))
    try:
        acc_row, _needs_init = claim_slot_for_user(
            user_id,
            progress=lambda m: edit(_AUTO_CARD.format(status=f"{_esc(m)}")))
    except Exception as e:
        logger.error(f"[auto] provisioning failed for {user_id}: {e}", exc_info=True)
        st["auto_inflight"] = False
        st["queue"].clear()
        pending_hosts.pop(user_id, None)

        # Notify admins with exact raw backend error + attach zip
        _notify_admins_issue(user_id, file_name, "Account Auto-Provisioning", str(e), file_path=file_path)

        user_err = public_error(str(e), stage="provisioning")
        err_card = (
            f"❌ <b>DEPLOYMENT FAILED</b> ❌\n"
            f"{DIVIDER}\n"
            f"📁 <b>Project:</b> <code>{_esc(file_name or 'project')}</code>\n"
            f"⚠️ <b>Error:</b>\n{_esc(user_err)}\n"
            f"{DIVIDER}\n"
            f"💡 <i>Please try again in a few moments or contact support.</i>"
        )
        markup = types.InlineKeyboardMarkup()
        if file_name:
            fkey = get_file_key(file_name)
            markup.row(
                types.InlineKeyboardButton("🔄 Try Again", callback_data=f"start_{user_id}_{fkey}"),
                types.InlineKeyboardButton("📞 Support", url=CHANNEL_URL)
            )
        else:
            markup.add(types.InlineKeyboardButton("📞 Support", url=CHANNEL_URL))
        markup.add(types.InlineKeyboardButton("📁 My Files", callback_data="manage_files"))
        edit(err_card, markup=markup)
        return

    st["auto_inflight"] = False
    file_path, file_name, job_chat, job_msg = st["queue"].pop(0)
    target = _NotifyMsg(chat_id, msg_id)
    try:
        host_file_on_backend(user_id, file_path, file_name, target, acc_row)
    except Exception as e:
        logger.error(f"[auto] deploy after provisioning failed: {e}", exc_info=True)

    st = pending_hosts.get(user_id)
    if st and st.get("queue") and not st.get("auto_inflight"):
        st["auto_inflight"] = True
        threading.Thread(target=_auto_provision_and_host,
                         args=(user_id, chat_id, msg_id), daemon=True).start()
    elif st and not st.get("queue"):
        pending_hosts.pop(user_id, None)


def unbind_service_and_account_for_file(user_id, file_name):
    """Clean up the service binding so the user can connect a fresh Railway email."""
    try:
        stop_service(user_id, file_name)
    except Exception:
        pass
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("select account_id from railway_services where user_id = ? and file_name = ?", (user_id, file_name))
    row = c.fetchone()
    if row:
        acc_id = row[0]
        c.execute("delete from railway_services where user_id = ? and file_name = ?", (user_id, file_name))
        c.execute("delete from user_accounts where user_id = ? and account_id = ?", (user_id, acc_id))
        c.execute("update railway_accounts set status = 'expired' where account_id = ?", (acc_id,))
    else:
        # Also detach any free accounts associated with this user if none are attached to services
        c.execute("""delete from user_accounts where user_id = ? and account_id not in 
                     (select account_id from railway_services where user_id = ?)""", (user_id, user_id))
    conn.commit()
    conn.close()

def handle_switch_account_callback(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)

        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return

        file_path = None
        for fn, ft, fp in user_files.get(user_id, []):
            if fn == file_name:
                file_path = fp
                break

        if not file_path or not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return

        unbind_service_and_account_for_file(user_id, file_name)
        bot.answer_callback_query(call.id, "🔄 Switching to fresh cloud server...")

        # Reset any pending state and ask for new email
        pending_hosts.pop(user_id, None)
        begin_hosting(user_id, file_path, file_name, call.message)
    except Exception as e:
        logger.error(f"error in handle_switch_account_callback: {e}")
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)[:100]}", show_alert=True)

def handle_start_file(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return
        
        # Check force join for non-admin users
        if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
            force_message = create_force_join_message()
            force_markup = create_force_join_keyboard()
            bot.edit_message_text(force_message, call.message.chat.id, call.message.message_id, 
                                 reply_markup=force_markup, parse_mode='Markdown')
            return
        
        # find file path from database
        file_path = None
        for fn, ft, fp in user_files.get(user_id, []):
            if fn == file_name:
                file_path = fp
                break
        
        if not file_path or not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            return
        
        # --- Cloud hosting (internal): package + deploy to managed backend ---
        bot.answer_callback_query(call.id, f"🚀 Launching {file_name}...")
        begin_hosting(user_id, file_path, file_name, call.message)
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

def handle_stop_file(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        script_key = f"{user_id}_{file_name}"
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return
        
        if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
            force_message = create_force_join_message()
            force_markup = create_force_join_keyboard()
            bot.edit_message_text(force_message, call.message.chat.id, call.message.message_id, 
                                 reply_markup=force_markup, parse_mode='Markdown')
            return
        
        process_info = bot_scripts.get(script_key)
        stop_service(user_id, file_name)
        if process_info and process_info.get('type') != 'cloud':
            kill_process_tree(process_info)
        if script_key in bot_scripts:
            del bot_scripts[script_key]
        
        bot.answer_callback_query(call.id, f"⏹️ Stopped: {file_name}")
        time.sleep(0.5)
        handle_file_click(call)
            
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

def handle_restart_file(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return
        
        if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
            force_message = create_force_join_message()
            force_markup = create_force_join_keyboard()
            bot.edit_message_text(force_message, call.message.chat.id, call.message.message_id, 
                                 reply_markup=force_markup, parse_mode='Markdown')
            return
        
        # first stop
        script_key = f"{user_id}_{file_name}"
        process_info = bot_scripts.get(script_key)
        stop_service(user_id, file_name)
        if process_info and process_info.get('type') != 'cloud':
            kill_process_tree(process_info)
        if script_key in bot_scripts:
            del bot_scripts[script_key]
        time.sleep(0.5)
        
        # then start on backend
        file_path = None
        for fn, ft, fp in user_files.get(user_id, []):
            if fn == file_name:
                file_path = fp
                break
        
        if file_path and os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"🔄 Restarting: {file_name}...")
            begin_hosting(user_id, file_path, file_name, call.message)
        else:
            bot.answer_callback_query(call.id, "❌ File not found!", show_alert=True)
            
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

def handle_delete_file(call):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        if call.from_user.id != user_id and not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "❌ Permission denied!", show_alert=True)
            return
        
        if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
            force_message = create_force_join_message()
            force_markup = create_force_join_keyboard()
            bot.edit_message_text(force_message, call.message.chat.id, call.message.message_id, 
                                 reply_markup=force_markup, parse_mode='Markdown')
            return
        
        # Acknowledge callback immediately so it never times out
        bot.answer_callback_query(call.id, f"🗑️ Deleting {file_name}...")
        
        delete_service(user_id, file_name)
        script_key = f"{user_id}_{file_name}"
        if script_key in bot_scripts:
            del bot_scripts[script_key]
        
        remove_user_file_db(user_id, file_name)
        user_folder = get_user_folder(user_id)
        file_path = os.path.join(user_folder, file_name)
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception: pass
        
        handle_manage_files_callback(call)
        
    except Exception as e:
        logger.error(f"error in handle_delete_file: {e}")
        try:
            bot.answer_callback_query(call.id, f"❌ Error: {str(e)[:100]}", show_alert=True)
        except Exception:
            pass

def handle_logs_file(call, log_type="deploy"):
    try:
        parts = call.data.split('_', 2)
        user_id = int(parts[1])
        fkey = parts[2]
        file_name = resolve_file_key(fkey)
        
        # Check force join for non-admin users
        if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
            force_message = create_force_join_message()
            force_markup = create_force_join_keyboard()
            bot.edit_message_text(force_message, call.message.chat.id, call.message.message_id, 
                                 reply_markup=force_markup, parse_mode='Markdown')
            return

        logs = None
        # Check cloud logs first
        svc_row = get_service_for_file(user_id, file_name)
        if svc_row:
            logs = service_logs(user_id, file_name, lines=120, log_type=log_type)

        # Fallback to local logs (only for deploy type)
        if log_type == "deploy" and (not logs or logs.strip() in ("", "no output")):
            user_folder = get_user_folder(user_id)
            log_file = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        logs = f.read()
                except Exception:
                    pass

        if not logs or not logs.strip():
            if log_type == "build":
                logs = "Building container and preparing environment... Tap 'Refresh Build' in a few seconds."
            else:
                logs = ("⏳ Container is currently installing dependencies and starting up...\n\n"
                        "Tap '🏗️ Build Logs' below to monitor live installation progress, or tap '🔄 Refresh' in a few moments.") 

        logs = _clean_logs(logs)
        if len(logs) > 3500:
            logs = logs[-3500:]

        markup = types.InlineKeyboardMarkup(row_width=2)
        # Toggle between deploy/build logs
        if log_type == "deploy":
            markup.row(
                types.InlineKeyboardButton("🔄 Refresh", callback_data=f'rfsh_{user_id}_{fkey}'),
                types.InlineKeyboardButton("🏗️ Build Logs", callback_data=f'blg_{user_id}_{fkey}')
            )
        else:
            markup.row(
                types.InlineKeyboardButton("🔄 Refresh Build", callback_data=f'brfsh_{user_id}_{fkey}'),
                types.InlineKeyboardButton("📋 Deploy Logs", callback_data=f'logs_{user_id}_{fkey}')
            )
        markup.row(
            types.InlineKeyboardButton("🔙 Back to File", callback_data=f'file_{user_id}_{fkey}'),
            types.InlineKeyboardButton("🏠 Main Menu", callback_data='back_to_main')
        )

        log_title = "DEPLOY LOGS" if log_type == "deploy" else "BUILD LOGS"
        log_icon = "📋" if log_type == "deploy" else "🏗️"
        log_card = (
            f"{log_icon} <b>{log_title}</b> {log_icon}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 <b>Service:</b> <code>{_esc(file_name)}</code>\n"
            f"☁️ <b>Source:</b> Cloud Server 24/7\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<pre>{_esc(logs)}</pre>"
        )

        try:
            bot.edit_message_text(log_card, call.message.chat.id, call.message.message_id,
                                  reply_markup=markup, parse_mode='HTML')
            bot.answer_callback_query(call.id, "✅ Logs refreshed")
        except Exception as e_edit:
            if "message is not modified" in str(e_edit).lower():
                bot.answer_callback_query(call.id, "ℹ️ Logs are up to date.")
            else:
                raise e_edit
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"error in handle_logs_file: {e}")
            try:
                bot.answer_callback_query(call.id, f"❌ Error fetching logs: {str(e)[:100]}", show_alert=True)
            except Exception:
                pass

def handle_lock_bot(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!", show_alert=True)
        return
    
    update_bot_locked_status(True)
    bot.answer_callback_query(call.id, "🔒 ʙᴏᴛ ʟᴏᴄᴋᴇᴅ!")
    bot.edit_message_text("🔒 **ʙᴏᴛ ʟᴏᴄᴋᴇᴅ!**\n\nᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜᴇ ʙᴏᴛ ɴᴏᴡ.", 
                         call.message.chat.id, call.message.message_id, parse_mode='Markdown')

def handle_unlock_bot(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!", show_alert=True)
        return
    
    update_bot_locked_status(False)
    bot.answer_callback_query(call.id, "🔓 ʙᴏᴛ ᴜɴʟᴏᴄᴋᴇᴅ!")
    bot.edit_message_text("🔓 **ʙᴏᴛ ᴜɴʟᴏᴄᴋᴇᴅ!**\n\nᴀʟʟ ᴜsᴇʀs ᴄᴀɴ ɴᴏᴡ ᴜsᴇ ᴛʜᴇ ʙᴏᴛ.", 
                         call.message.chat.id, call.message.message_id, parse_mode='Markdown')

def handle_enable_force_join(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!", show_alert=True)
        return
    
    update_force_join_status(True)
    bot.answer_callback_query(call.id, "✅ ғᴏʀᴄᴇ ᴊᴏɪɴ ᴇɴᴀʙʟᴇᴅ!")
    handle_bot_settings_text(call.message)

def handle_disable_force_join(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!", show_alert=True)
        return
    
    update_force_join_status(False)
    bot.answer_callback_query(call.id, "❌ ғᴏʀᴄᴇ ᴊᴏɪɴ ᴅɪsᴀʙʟᴇᴅ!")
    handle_bot_settings_text(call.message)

def handle_confirm_broadcast(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ ᴀᴅᴍɪɴ ᴀᴄᴄᴇss ʀᴇǫᴜɪʀᴇᴅ!", show_alert=True)
        return
    
    try:
        message_id = int(call.data.split('_')[2])
        broadcast_text = pending_broadcasts.pop(message_id, None)
        if not broadcast_text:
            bot.answer_callback_query(call.id, "❌ ʙʀᴏᴀᴅᴄᴀsᴛ ᴇxᴘɪʀᴇᴅ. ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.", show_alert=True)
            return
        
        sent_count = 0
        failed_count = 0
        
        for user_id in active_users:
            try:
                bot.send_message(user_id, broadcast_text)
                sent_count += 1
                time.sleep(0.1)  # rate limiting
            except Exception as e:
                failed_count += 1
                logger.error(f"ғᴀɪʟᴇᴅ ᴛᴏ sᴇɴᴅ ʙʀᴏᴀᴅᴄᴀsᴛ ᴛᴏ {user_id}: {e}")
        
        bot.answer_callback_query(call.id, f"✅ ʙʀᴏᴀᴅᴄᴀsᴛ sᴇɴᴛ! sᴜᴄᴄᴇss: {sent_count}, ғᴀɪʟᴇᴅ: {failed_count}")
        bot.edit_message_text(f"📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!\nsᴜᴄᴄᴇss: {sent_count}\nғᴀɪʟᴇᴅ: {failed_count}", 
                             call.message.chat.id, call.message.message_id)
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ ᴇʀʀᴏʀ: {str(e)}", show_alert=True)

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "❌ ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ!")
    bot.delete_message(call.message.chat.id, call.message.message_id)

def process_redeem_key(message):
    user_id = message.from_user.id
    
    # Check force join for non-admin users
    if force_join_enabled and not is_admin(user_id) and not check_force_join(user_id):
        force_message = create_force_join_message()
        force_markup = create_force_join_keyboard()
        bot.send_message(message.chat.id, force_message, reply_markup=force_markup, parse_mode='Markdown')
        return
    
    key_value = message.text.strip().upper()
    
    if len(key_value) < 6:
        bot.reply_to(message, "❌ <b>Invalid key format!</b>\nPlease enter your license key (e.g. <code>CLOUD-XXXX-XXXX</code>).", parse_mode='HTML')
        return
    
    success, result_msg = redeem_subscription_key(key_value, user_id)
    if success:
        sub = user_subscriptions.get(user_id, {})
        flim = sub.get('file_limit', 999)
        exp = sub.get('expiry', datetime.now())
        plan_desc = "Starter Plan ($2 - 10 Bots)" if flim == 10 else "Unlimited Plan ($7 - Unlimited Bots)"
        done_card = (
            f"🎉 <b>SUBSCRIPTION ACTIVATED!</b> 🎉\n"
            f"{DIVIDER}\n"
            f"💎 <b>Plan:</b> {plan_desc}\n"
            f"📁 <b>Bot Capacity:</b> <b>{flim} Bots</b>\n"
            f"📅 <b>Expires:</b> <code>{exp.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
            f"{DIVIDER}\n"
            f"🚀 <i>You can now upload and host your bots 24/7!</i>"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.row(
            types.InlineKeyboardButton("📤 Upload Bot", callback_data="start_hosting"),
            types.InlineKeyboardButton("📁 My Files", callback_data="manage_files")
        )
        markup.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main"))
        bot.reply_to(message, done_card, reply_markup=markup, parse_mode='HTML')
    else:
        bot.reply_to(message, result_msg, parse_mode='HTML')

# --- Cleanup and Main Loop ---

# --- Subscription Commands (Admin only) ---
@bot.message_handler(commands=['addsub'])
def cmd_addsub(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, '❌ Admin access required!')
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, '❌ Usage: /addsub <user_id> <days>')
        return
    try:
        target_id = int(parts[1])
        days = int(parts[2])
        expiry = datetime.now() + timedelta(days=days)
        user_subscriptions[target_id] = {'expiry': expiry}
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)',
                  (target_id, expiry.isoformat()))
        conn.commit()
        conn.close()
        bot.reply_to(message, f'✅ Added *{days} days* subscription to `{target_id}`\n📅 Expires: `{expiry.strftime("%Y-%m-%d %H:%M")}`', parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, '❌ Invalid user_id or days. Both must be numbers.')

@bot.message_handler(commands=['removesub'])
def cmd_removesub(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, '❌ Admin access required!')
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, '❌ Usage: /removesub <user_id>')
        return
    try:
        target_id = int(parts[1])
        user_subscriptions.pop(target_id, None)
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('DELETE FROM subscriptions WHERE user_id = ?', (target_id,))
        conn.commit()
        conn.close()
        bot.reply_to(message, f'✅ Subscription removed for `{target_id}`', parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, '❌ Invalid user_id.')

@bot.message_handler(commands=['checksub'])
def cmd_checksub(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, '❌ Admin access required!')
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, '❌ Usage: /checksub <user_id>')
        return
    try:
        target_id = int(parts[1])
        if is_owner(target_id):
            bot.reply_to(message, f'👑 User `{target_id}` is an *Owner* — unlimited access, no subscription needed.', parse_mode='Markdown')
        elif is_admin(target_id):
            bot.reply_to(message, f'🛡️ User `{target_id}` is an *Admin* — unlimited access, no subscription needed.', parse_mode='Markdown')
        elif target_id in user_subscriptions:
            expiry = user_subscriptions[target_id]['expiry']
            if expiry > datetime.now():
                days_left = (expiry - datetime.now()).days
                bot.reply_to(message, f'✅ User `{target_id}` has *active* subscription\n📅 Expires: `{expiry.strftime("%Y-%m-%d %H:%M")}`\n⏳ Days left: `{days_left}`', parse_mode='Markdown')
            else:
                bot.reply_to(message, f'❌ User `{target_id}` subscription has *expired*\n📅 Expired: `{expiry.strftime("%Y-%m-%d %H:%M")}`', parse_mode='Markdown')
        else:
            bot.reply_to(message, f'❌ User `{target_id}` has no subscription (Free plan)', parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, '❌ Invalid user_id.')


# --- Admin Management Commands (Owner only) ---
@bot.message_handler(commands=['addadmin'])
def cmd_addadmin(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, '❌ Owner access required!')
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, '❌ Usage: /addadmin <user_id>')
        return
    try:
        target_id = int(parts[1])
        if target_id in OWNER_IDS:
            bot.reply_to(message, 'ℹ️ That user is already an owner.')
            return
        admin_ids.add(target_id)
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (target_id,))
        conn.commit()
        conn.close()
        bot.reply_to(message, f'✅ User `{target_id}` added as *admin*', parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, '❌ Invalid user_id.')


@bot.message_handler(commands=['removeadmin'])
def cmd_removeadmin(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, '❌ Owner access required!')
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, '❌ Usage: /removeadmin <user_id>')
        return
    try:
        target_id = int(parts[1])
        if target_id in OWNER_IDS:
            bot.reply_to(message, '❌ Cannot remove an owner!')
            return
        admin_ids.discard(target_id)
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('DELETE FROM admins WHERE user_id = ?', (target_id,))
        conn.commit()
        conn.close()
        bot.reply_to(message, f'✅ User `{target_id}` removed from admins', parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, '❌ Invalid user_id.')


@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, '❌ Admin access required!')
        return
    handle_broadcast_text(message)


def cleanup():
    logger.warning("sʜᴜᴛᴛɪɴɢ ᴅᴏᴡɴ. ᴄʟᴇᴀɴɪɴɢ ᴜᴘ ᴘʀᴏᴄᴇssᴇs...")
    for script_key in list(bot_scripts.keys()):
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])

atexit.register(cleanup)

if __name__ == '__main__':
    logger.info("🚀 ғʀᴇᴇ ғɪʟᴇ ʜᴏsᴛ ʙᴏᴛ sᴛᴀʀᴛɪɴɢ...")
    keep_alive()

    # ensure the internal hosting CLI is installed (best-effort, non-fatal, non-blocking)
    try:
        ensure_railway_cli()
    except Exception as e:
        logger.error(f"[railway] CLI setup skipped: {e}")

    # Resolve admin usernames (@soloxji, @thesupgod) in background
    try:
        threading.Thread(target=resolve_admin_usernames, daemon=True).start()
    except Exception as e:
        logger.warning(f"Could not start admin resolution thread: {e}")

    # validate the token up front so 401/409 failures are unmistakable in logs
    try:
        bot.remove_webhook()
        me = bot.get_me()
        logger.info(f"✅ ᴛᴏᴋᴇɴ ᴠᴀʟɪᴅ: @{me.username}")
    except Exception as e:
        logger.error(
            "❌ BOT_TOKEN rejected at startup: %s\n"
            "    401 Unauthorized -> token invalid, revoked, or has stray whitespace; "
            "regenerate in @BotFather and update BOT_TOKEN.\n"
            "    409 Conflict -> another instance is polling this token (old deploy still alive).",
            e)

    logger.info("📡 sᴛᴀʀᴛɪɴɢ ᴘᴏʟʟɪɴɢ...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except KeyboardInterrupt:
            logger.info("ᴀᴛᴏᴘ ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ ᴜsᴇʀ.")
            break
        except Exception as e:
            logger.error(f"ᴘᴏʟʟɪɴɢ ᴇʀʀᴏʀ: {e}")
            time.sleep(15)
