"""
J3A Discord Profile - Web Panel (Flask)
เปิดหน้าเว็บควบคุมแบบ App Mode ไร้แถบ URL เสมือนเปิดโปรแกรมเดสก์ท็อป
"""

import os
import sys
import re
import json
import urllib.request
import urllib.parse
import datetime
import subprocess
import threading
import time
import webbrowser

from flask import Flask, jsonify, request, send_from_directory, send_file

# PyInstaller & Windows Compatibility
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w")
    except Exception:
        pass

if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("J3A.DiscordProfile.App.1.0")
    except Exception:
        pass

import main as core
from main import FORM_KEYS, URL_RE, RPCWorker, Store, friendly_error, get_resource_path
import license_manager

HOST, PORT = "127.0.0.1", 5000
MIN_TS = int(datetime.datetime(1999, 1, 1).timestamp())  # เลือกได้ตั้งแต่ 1 ม.ค. 1999

template_dir = get_resource_path("templates")
app = Flask(__name__, template_folder=template_dir)
store = Store()
lock = threading.RLock()

S = {
    "state": "off",       # off | connecting | online
    "worker": None,
    "form": {},
    "show_time": True,
    "chosen_ts": None,    # เวลาเริ่มที่ผู้ใช้เลือก (None = ตอนเชื่อมต่อสำเร็จ)
    "start_ts": None,     # เวลาเริ่มที่ใช้งานจริง
    "logs": [],
    "seq": 0,
}


def log(msg, lvl="info"):
    with lock:
        S["seq"] += 1
        S["logs"].append({"id": S["seq"], "t": time.strftime("%H:%M:%S"), "lvl": lvl, "msg": msg})
        del S["logs"][:-300]


_ASSET_CACHE = {}


def get_app_metadata(client_id, force=False):
    if not client_id or not str(client_id).isdigit():
        return {"name": "", "icon_url": "", "assets": []}
    cid = str(client_id).strip()
    now = time.time()
    cached = _ASSET_CACHE.get(cid)
    if not force and cached and (now - cached["ts"] < 30):
        return cached["data"]

    name = ""
    icon_url = ""
    assets = []

    # 1. ดึงชื่อแอปและไอคอนแอปปัจจุบันจาก Discord OAuth2 RPC API
    try:
        rpc_url = f"https://discord.com/api/v9/oauth2/applications/{cid}/rpc"
        req = urllib.request.Request(rpc_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            info = json.loads(resp.read().decode())
            name = str(info.get("name") or "")
            icon_hash = str(info.get("icon") or "").strip()
            if icon_hash:
                ext = "gif" if icon_hash.startswith("a_") else "png"
                icon_url = f"https://cdn.discordapp.com/app-icons/{cid}/{icon_hash}.{ext}?size=512"
    except Exception:
        if cached:
            name = cached["data"].get("name", "")
            icon_url = cached["data"].get("icon_url", "")

    # 2. ดึงรายการ Art Assets จาก Discord API
    try:
        url = f"https://discord.com/api/v9/oauth2/applications/{cid}/assets"
        req2 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=4) as resp2:
            raw = json.loads(resp2.read().decode())
            assets = [
                {
                    "id": str(a.get("id")),
                    "name": str(a.get("name")),
                    "url": f"https://cdn.discordapp.com/app-assets/{cid}/{a.get('id')}.png",
                }
                for a in raw
                if a.get("name") and a.get("id")
            ]
    except Exception:
        if cached:
            assets = cached["data"].get("assets", [])

    data = {"name": name, "icon_url": icon_url, "assets": assets}
    _ASSET_CACHE[cid] = {"ts": now, "data": data}
    return data


def get_app_assets(client_id, force=False):
    return get_app_metadata(client_id, force=force).get("assets", [])


def normalize_image_key(val, client_id, is_large=True, force=False):
    val = (val or "").strip()
    meta = get_app_metadata(client_id, force=force) if client_id else {"name": "", "icon_url": "", "assets": []}
    assets = meta.get("assets", [])
    icon_url = meta.get("icon_url", "")

    # กรณีผู้ใช้ไม่ได้กรอกช่องรูปใหญ่ (เว้นว่าง) หรือเลือก @app_icon
    # ให้ดึงไอคอนแอปปัจจุบัน หรือ Art Asset ล่าสุดมาใส่อัตโนมัติ เพื่อไม่ให้ติดรูปแคชเก่าของ Discord
    if not val or val == "@app_icon":
        if not is_large and not val:
            return ""
        if icon_url:
            return icon_url
        if assets:
            return assets[-1]["name"]
        return ""

    # หากผู้ใช้นำลิงก์ Discord App Asset มาแปะ หรือใส่เลข Asset ID มา ให้แปลงเป็นชื่อ Asset Key
    m = re.search(r"cdn\.discordapp\.com/app-assets/\d+/(\d+)", val)
    target_id = m.group(1) if m else (val if val.isdigit() else None)
    if target_id:
        for a in assets:
            if a["id"] == target_id:
                return a["name"]
    return val


# ── Validation (พอร์ตจาก App.validate ใน main.py) ──────────────
def build_payload(form, show_time, start_ts, force_refresh=False):
    v = lambda k: str(form.get(k, "") or "").strip()
    errors = []

    cid = v("client_id")
    if cid and not (cid.isdigit() and 17 <= len(cid) <= 20):
        errors.append("Application ID ต้องเป็นตัวเลข 17–20 หลัก")

    # Details & State (ถ้ากรอก 1 ตัวอักษรให้เติมเว้นวรรคเพื่อไม่ให้ Discord API ปฏิเสธ)
    details = v("details")
    if len(details) == 1:
        details = details + " "
    elif len(details) > 128:
        details = details[:128]

    state = v("state")
    if len(state) == 1:
        state = state + " "
    elif len(state) > 128:
        state = state[:128]

    large_img = normalize_image_key(v("large_image"), cid, is_large=True, force=force_refresh)
    small_img = normalize_image_key(v("small_image"), cid, is_large=False, force=False)
    if small_img and not large_img:
        large_img = small_img

    buttons = []
    for i in (1, 2):
        lt, lu = v(f"btn{i}_text"), v(f"btn{i}_url")
        # ใส่ปุ่มเฉพาะเมื่อกรอกครบทั้งชื่อและ URL (ถ้าไม่ใส่หรือกรอกค้างไว้ จะข้ามไปโดยไม่บล็อกการเชื่อมต่อ)
        if lt and lu:
            if not lu.startswith(("http://", "https://")):
                lu = "https://" + lu
            if URL_RE.match(lu):
                buttons.append({"label": lt[:32], "url": lu[:512]})

    act_key = (v("activity_type") or "competing").lower()
    try:
        from pypresence import ActivityType
        act_map = {
            "competing": ActivityType.COMPETING,
            "playing": ActivityType.PLAYING,
            "listening": ActivityType.LISTENING,
            "watching": ActivityType.WATCHING,
        }
        act_type = act_map.get(act_key, ActivityType.COMPETING)
    except Exception:
        act_type = None

    payload = {}
    if act_type is not None:
        payload["activity_type"] = act_type
    if details:
        payload["details"] = details
    if state:
        payload["state"] = state
    if large_img:
        payload["large_image"] = large_img
        if v("large_text"):
            payload["large_text"] = v("large_text")[:128]
    if small_img:
        payload["small_image"] = small_img
        if v("small_text"):
            payload["small_text"] = v("small_text")[:128]
    if show_time and start_ts:
        payload["start"] = start_ts
    if buttons:
        payload["buttons"] = buttons

    return payload, errors


def parse_request():
    """อ่านค่าจาก request -> (form, show_time, chosen_ts, error)"""
    d = request.get_json(force=True, silent=True) or {}
    form = {k: str((d.get("form") or {}).get(k, "") or "").strip() for k in FORM_KEYS}
    for i in (1, 2):
        u = form.get(f"btn{i}_url", "").strip()
        if u and not u.startswith(("http://", "https://")):
            form[f"btn{i}_url"] = "https://" + u
    show = bool(d.get("show_time", True))
    ts = d.get("start_ts")
    if ts in (None, ""):
        return form, show, None, None
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return form, show, None, "รูปแบบเวลาเริ่มไม่ถูกต้อง"
    if ts < MIN_TS:
        return form, show, None, "เลือกเวลาได้ตั้งแต่ปี 1999 เป็นต้นไป"
    if ts > int(time.time()) + 60:
        return form, show, None, "เวลาเริ่มต้องไม่เกินเวลาปัจจุบัน"
    return form, show, ts, None


def persist():
    store.data["form"] = {**S["form"], "show_time": S["show_time"], "start_ts": S["chosen_ts"]}
    store.save()


def push_update():
    w = S["worker"]
    if S["state"] != "online" or not w:
        return False
    payload, errors = build_payload(S["form"], S["show_time"], S["start_ts"], force_refresh=True)
    if errors:
        log(errors[0], "warn")
        return False
    w.q.put(("update", payload))
    return True


# ── Worker events (พอร์ตจาก App._on_rpc) ────────────────────────
def on_rpc(worker, ev, data):
    with lock:
        if worker is not S["worker"]:
            return
        if ev == "connected":
            S["start_ts"] = (S["chosen_ts"] or int(time.time())) if S["show_time"] else None
            S["state"] = "online"
            log("เชื่อมต่อ Discord สำเร็จ!", "ok")
            push_update()
        elif ev == "updated":
            log("อัปเดตสถานะสำเร็จ", "ok")
        elif ev == "failed":
            msg = friendly_error(data)
            S["worker"], S["state"], S["start_ts"] = None, "off", None
            log(f"เชื่อมต่อไม่สำเร็จ: {msg}", "err")
        elif ev == "error":
            e, lost = data
            log(f"เกิดข้อผิดพลาดในการอัปเดต: {friendly_error(e)}", "err")
            if lost:
                S["worker"], S["state"], S["start_ts"] = None, "off", None


# ── Routes ───────────────────────────────────────────────────
@app.get("/")
def index():
    # ส่งเป็นไฟล์ตรงๆ (ไม่ผ่าน Jinja เพราะ JSX ใช้ {{ }})
    return send_from_directory(app.template_folder, "index.html")


@app.get("/logo.png")
@app.get("/J3ADiscordProfileLogo.png")
def get_logo():
    logo_file = get_resource_path("J3ADiscordProfileLogo.png")
    return send_file(logo_file, mimetype="image/png")


@app.get("/favicon.ico")
def get_favicon():
    ico_file = get_resource_path("app_icon.ico")
    return send_file(ico_file, mimetype="image/x-icon")


APP_VERSION = "1.2.0"
DEFAULT_VERSION_INFO = {
    "version": APP_VERSION,
    "release_date": "2026-10-06",
    "github_repo": "Newwee/J3ADiscordProfile",
    "version_check_url": "https://raw.githubusercontent.com/Newwee/J3ADiscordProfile/main/version.json",
    "download_url": "https://github.com/Newwee/J3ADiscordProfile/releases/latest/download/J3ADiscordProfile.exe",
    "drive_url": "https://drive.google.com/file/d/18Mt5mytIu-jB7Jt7efyr_nTxWGkDTuV0/view?usp=drive_link",
    "changelog": [
        "เพิ่มระบบ Priority Mode (Competing) ให้แอปแสดงอยู่บนสุดของหน้าโปรไฟล์เสมอ ทับทุกเกม 100%",
        "ซิงค์รูปไอคอนแอปหลักและ Art Assets ล่าสุดจาก Discord อัตโนมัติ (แก้ปัญหารูปติดแคชเก่า)",
        "เพิ่มปุ่มตรวจสอบเวอร์ชัน (Check Version) พร้อมระบบอัปเดตอัตโนมัติในคลิกเดียว",
        "เพิ่มปุ่มถอนการติดตั้งโปรแกรม (Uninstaller) ล้างไฟล์และทางลัดหน้าจอครบวงจร",
    ],
}


def _parse_ver(v_str):
    parts = re.findall(r"\d+", str(v_str or "0"))
    return tuple(int(x) for x in (parts + ["0", "0", "0"])[:3])


def get_local_version_info():
    info = dict(DEFAULT_VERSION_INFO)
    try:
        v_path = get_resource_path("version.json")
        if os.path.exists(v_path):
            with open(v_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    info.update(loaded)
    except Exception:
        pass
    return info


@app.get("/api/version/check")
def api_version_check():
    local_info = get_local_version_info()
    current_v = str(local_info.get("version") or APP_VERSION).lstrip("vV")
    latest_v = current_v
    release_date = local_info.get("release_date", "2026-10-06")
    changelog = local_info.get("changelog", [])
    download_url = local_info.get("download_url", "")
    drive_url = local_info.get("drive_url", "")
    repo = local_info.get("github_repo", "")
    check_url = local_info.get("version_check_url", "")

    remote_found = False
    # 1. ตรวจสอบจาก version.json บน GitHub Raw ก่อน
    if check_url:
        try:
            url = f"{check_url}?t={int(time.time())}"
            req = urllib.request.Request(url, headers={"User-Agent": "J3ADiscordProfile-Updater/1.2"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                rem = json.loads(resp.read().decode("utf-8"))
                if isinstance(rem, dict) and rem.get("version"):
                    latest_v = str(rem["version"]).lstrip("vV")
                    release_date = rem.get("release_date") or release_date
                    changelog = rem.get("changelog") or changelog
                    download_url = rem.get("download_url") or download_url
                    drive_url = rem.get("drive_url") or drive_url
                    remote_found = True
        except Exception:
            pass

    # 2. หากยังไม่มี ให้ลองตรวจสอบจาก GitHub Releases API
    if not remote_found and repo:
        try:
            rel_url = f"https://api.github.com/repos/{repo}/releases/latest"
            req = urllib.request.Request(rel_url, headers={"User-Agent": "J3ADiscordProfile-Updater/1.2"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                rel = json.loads(resp.read().decode("utf-8"))
                tag = str(rel.get("tag_name") or "").lstrip("vV")
                if tag:
                    latest_v = tag
                    body_lines = [line.strip("-* \t") for line in str(rel.get("body") or "").splitlines() if line.strip()]
                    if body_lines:
                        changelog = body_lines
                    for asset in rel.get("assets") or []:
                        if str(asset.get("name", "")).lower().endswith((".exe", ".zip")):
                            download_url = asset.get("browser_download_url") or download_url
                            break
                    remote_found = True
        except Exception:
            pass

    has_update = _parse_ver(latest_v) > _parse_ver(current_v)
    if has_update:
        log(f"พบเวอร์ชันใหม่ v{latest_v} (ปัจจุบัน v{current_v})", "info")
    else:
        log(f"ตรวจสอบเวอร์ชันแล้ว: คุณกำลังใช้เวอร์ชันล่าสุด (v{current_v})", "ok")

    return jsonify(
        ok=True,
        current_version=current_v,
        latest_version=latest_v,
        has_update=has_update,
        release_date=release_date,
        changelog=changelog,
        download_url=download_url,
        drive_url=drive_url,
        checked_at=time.strftime("%H:%M:%S"),
    )


@app.post("/api/version/update")
def api_version_update():
    """ดาวน์โหลดไฟล์ .exe เวอร์ชันใหม่จาก GitHub และเขียนทับตัวเองพร้อมเปิดแอปใหม่อัตโนมัติ"""
    data = request.get_json(silent=True) or {}
    local_info = get_local_version_info()
    dl_url = str(data.get("download_url") or local_info.get("download_url") or "").strip()
    drive_url = str(local_info.get("drive_url") or "").strip()

    if not getattr(sys, "frozen", False):
        return jsonify(
            ok=False,
            error="โหมดนักพัฒนา (Python Source): กรุณาใช้ git pull เพื่ออัปเดตโค้ด หรือดาวน์โหลดจากลิงก์",
            open_url=drive_url,
        )

    exe_path = os.path.abspath(sys.executable)
    exe_dir = os.path.dirname(exe_path)
    tmp_exe = os.path.join(exe_dir, "J3ADiscordProfile_update.exe")

    try:
        log("กำลังดาวน์โหลดเวอร์ชันใหม่…", "info")
        req = urllib.request.Request(dl_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        if len(content) < 500_000 or not content.startswith(b"MZ"):
            raise ValueError("ไฟล์ที่ดาวน์โหลดไม่ใช่ไฟล์ .exe ที่สมบูรณ์")
        with open(tmp_exe, "wb") as f:
            f.write(content)
    except Exception as e:
        if os.path.exists(tmp_exe):
            try:
                os.remove(tmp_exe)
            except Exception:
                pass
        return jsonify(
            ok=False,
            error=f"ไม่สามารถดาวน์โหลดอัตโนมัติได้ ({e}) ระบบจะเปิดลิงก์ดาวน์โหลดให้แทน",
            open_url=drive_url,
        )

    # สร้างสคริปต์ .bat ใน %TEMP% เพื่อรอให้โปรเซสเก่าปิด แล้วแทนที่ไฟล์ .exe และเปิดใหม่ทันที
    import tempfile
    bat_path = os.path.join(tempfile.gettempdir(), "j3a_self_update.bat")
    bat_content = f"""@echo off
chcp 65001 >nul
timeout /t 2 /nobreak >nul
taskkill /F /IM "J3ADiscordProfile.exe" >nul 2>&1
timeout /t 1 /nobreak >nul
move /Y "{tmp_exe}" "{exe_path}" >nul 2>&1
start "" "{exe_path}"
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    with lock:
        if S["worker"]:
            S["worker"].q.put(("stop", None))
    log("ดาวน์โหลดสำเร็จ! กำลังรีสตาร์ทเพื่อติดตั้งเวอร์ชันใหม่…", "ok")
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
    )
    threading.Timer(0.6, lambda: os._exit(0)).start()
    return jsonify(ok=True, message="กำลังติดตั้งอัปเดตและเปิดโปรแกรมใหม่…")


@app.post("/api/uninstall")
def api_uninstall():
    """ถอนการติดตั้ง: ปิด RPC, ลบทางลัดหน้าจอ Desktop, ลบข้อมูลใน %APPDATA% และลบตัวโปรแกรม"""
    import shutil
    import tempfile

    with lock:
        if S["worker"]:
            S["worker"].q.put(("stop", None))
        S.update(worker=None, state="off", start_ts=None)

    # 1. ลบไอคอนทางลัดบน Desktop (ทั้ง Desktop ปกติ และ OneDrive Desktop)
    user_prof = os.environ.get("USERPROFILE", "")
    desktop_candidates = [
        os.path.join(user_prof, "Desktop"),
        os.path.join(user_prof, "OneDrive", "Desktop"),
    ]
    for d_dir in desktop_candidates:
        for sc_name in ("J3A Discord Profile.lnk", "J3ADiscordProfile.lnk"):
            sc_path = os.path.join(d_dir, sc_name)
            if os.path.exists(sc_path):
                try:
                    os.remove(sc_path)
                except Exception:
                    pass

    # 2. เตรียมพาธโฟลเดอร์ข้อมูล %APPDATA%\J3ADiscordProfile
    appdata_dir = str(license_manager.get_license_dir())
    try:
        shutil.rmtree(appdata_dir, ignore_errors=True)
    except Exception:
        pass

    # 3. สร้างสคริปต์ลบไฟล์หลังโปรแกรมปิดตัวลง
    exe_path = os.path.abspath(sys.executable) if getattr(sys, "frozen", False) else ""
    exe_dir = os.path.dirname(exe_path) if exe_path else ""
    # ป้องกันการลบโฟลเดอร์โปรเจกต์ต้นฉบับของนักพัฒนา
    is_dev_workspace = bool(exe_dir and os.path.exists(os.path.join(exe_dir, "server.py")))

    bat_path = os.path.join(tempfile.gettempdir(), "j3a_uninstall_cleanup.bat")
    del_exe_cmds = ""
    if exe_path and not is_dev_workspace:
        del_exe_cmds = f"""
del /F /Q "{exe_path}" >nul 2>&1
del /F /Q "{os.path.join(exe_dir, 'สร้างไอคอนหน้าจอ_Desktop.bat')}" >nul 2>&1
del /F /Q "{os.path.join(exe_dir, 'ถอนการติดตั้ง_Uninstall.bat')}" >nul 2>&1
del /F /Q "{os.path.join(exe_dir, 'วิธีใช้งาน_คู่มือเริ่มต้น.txt')}" >nul 2>&1
"""

    bat_content = f"""@echo off
chcp 65001 >nul
timeout /t 2 /nobreak >nul
taskkill /F /IM "J3ADiscordProfile.exe" >nul 2>&1
timeout /t 1 /nobreak >nul
rmdir /S /Q "{appdata_dir}" >nul 2>&1
{del_exe_cmds}
powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('ถอนการติดตั้ง J3A Discord Profile และล้างข้อมูลในเครื่องเรียบร้อยแล้ว', 'J3A Discord Profile - Uninstaller', 'OK', 'Information')" >nul 2>&1
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
    )
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify(ok=True, message="กำลังถอนการติดตั้งและล้างข้อมูลทั้งหมด…")


@app.post("/api/shutdown")
def api_shutdown():
    with lock:
        if S["worker"]:
            S["worker"].q.put(("stop", None))
    log("ปิดโปรแกรมเรียบร้อยแล้ว", "info")
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify(ok=True)


@app.get("/api/discord/assets")
def api_discord_assets():
    cid = request.args.get("client_id", "").strip()
    force = request.args.get("force", "0") == "1"
    if not cid:
        return jsonify(ok=False, app_name="", app_icon="", assets=[])
    meta = get_app_metadata(cid, force=force)
    return jsonify(
        ok=True,
        app_name=meta.get("name", ""),
        app_icon=meta.get("icon_url", ""),
        assets=meta.get("assets", []),
    )


# ── License Routes ──────────────────────────────────────────
@app.get("/api/license/status")
def api_license_status():
    cached_only = request.args.get("fast", "0") == "1"
    is_active, msg, masked_key = license_manager.verify_license(cached_only=cached_only)
    return jsonify(
        activated=is_active,
        hwid=license_manager.get_hwid(),
        key=masked_key,
        message=msg,
    )


@app.post("/api/license/activate")
def api_license_activate():
    data = request.get_json(silent=True) or {}
    key = str(data.get("key") or "").strip().upper()
    if not key:
        return jsonify(ok=False, error="กรุณากรอก License Key"), 400

    ok, msg = license_manager.activate_license(key)
    if ok:
        log(f"เปิดใช้งาน License Key สำเร็จ: {license_manager.mask_key(key)}", "ok")
        return jsonify(
            ok=True,
            message=msg,
            hwid=license_manager.get_hwid(),
            key=license_manager.mask_key(key),
        )
    else:
        log(f"เปิดใช้งาน License ไม่สำเร็จ: {msg}", "warn")
        return jsonify(ok=False, error=msg), 400


@app.post("/api/license/logout")
@app.post("/api/license/deactivate")
def api_license_logout():
    with lock:
        if S["worker"]:
            S["worker"].q.put(("stop", None))
        S.update(worker=None, state="off", start_ts=None)
    license_manager.delete_cached_license()
    log("ออกจากระบบและถอนคีย์บนเครื่องนี้เรียบร้อยแล้ว", "info")
    return jsonify(ok=True, message="ออกจากระบบเรียบร้อยแล้ว")


@app.get("/api/state")
def api_state():
    since = int(request.args.get("since", 0) or 0)
    with lock:
        is_active, msg, masked_key = license_manager.verify_license(cached_only=True)
        if not is_active:
            # ป้องกันการดึงข้อมูลสถานะหากยังไม่ได้เปิดใช้งาน License
            return jsonify(
                state="off",
                start_ts=None,
                now=int(time.time()),
                min_ts=MIN_TS,
                saved={},
                saved_show_time=True,
                saved_start_ts=None,
                logs=[],
                license={
                    "activated": False,
                    "hwid": license_manager.get_hwid(),
                    "key": "",
                    "message": msg,
                },
            )
        saved = store.data.get("form", {})
        return jsonify(
            state=S["state"],
            start_ts=S["start_ts"],
            now=int(time.time()),
            min_ts=MIN_TS,
            saved={k: saved.get(k, "") for k in FORM_KEYS},
            saved_show_time=saved.get("show_time", True) is not False,
            saved_start_ts=saved.get("start_ts"),
            logs=[x for x in S["logs"] if x["id"] > since],
            license={
                "activated": True,
                "hwid": license_manager.get_hwid(),
                "key": masked_key,
                "message": msg,
            },
        )


@app.post("/api/start")
def api_start():
    # ตรวจสอบ License Key ก่อนเชื่อมต่อ
    is_active, lic_msg, _ = license_manager.verify_license(cached_only=False)
    if not is_active:
        log(f"ไม่สามารถเริ่มใช้งานได้: {lic_msg}", "warn")
        return jsonify(ok=False, error=f"กรุณาเปิดใช้งาน License Key ก่อนเริ่มใช้งาน ({lic_msg})"), 403

    form, show, ts, err = parse_request()
    with lock:
        if S["state"] != "off":
            return jsonify(ok=False, error="กำลังทำงานอยู่แล้ว"), 409
        if err:
            log(err, "warn")
            return jsonify(ok=False, error=err), 400
        if not form["client_id"]:
            log("ข้อผิดพลาด: ยังไม่ได้กรอก Application ID", "warn")
            return jsonify(ok=False, error="กรุณากรอก Application ID"), 400
        _, errors = build_payload(form, show, ts)
        if errors:
            log(errors[0], "warn")
            return jsonify(ok=False, error=errors[0]), 400

        S.update(form=form, show_time=show, chosen_ts=ts)
        core.START_OVERRIDE["ts"] = ts
        persist()
        log("กำลังเชื่อมต่อไปยัง Discord Desktop…", "info")
        S["state"] = "connecting"
        w = RPCWorker(form["client_id"])
        w.notify = lambda ev, data=None, w=w: on_rpc(w, ev, data)
        S["worker"] = w
        w.start()
    return jsonify(ok=True)


@app.post("/api/update")
def api_update():
    is_active, lic_msg, _ = license_manager.verify_license(cached_only=True)
    if not is_active:
        return jsonify(ok=False, error=f"License ไม่ถูกต้อง: {lic_msg}"), 403

    form, show, ts, err = parse_request()
    with lock:
        if err:
            return jsonify(ok=False, error=err), 400
        if S["state"] != "online":
            return jsonify(ok=False, error="ยังไม่ได้เชื่อมต่อ Discord"), 409
        _, errors = build_payload(form, show, ts)
        if errors:
            log(errors[0], "warn")
            return jsonify(ok=False, error=errors[0]), 400
        S.update(form=form, show_time=show, chosen_ts=ts)
        core.START_OVERRIDE["ts"] = ts
        S["start_ts"] = (ts or S["start_ts"] or int(time.time())) if show else None
        persist()
        push_update()
    return jsonify(ok=True)


@app.post("/api/stop")
def api_stop():
    with lock:
        if S["worker"]:
            S["worker"].q.put(("stop", None))
        S.update(worker=None, state="off", start_ts=None)
        log("ตัดการเชื่อมต่อและปิดสถานะแล้ว", "info")
    return jsonify(ok=True)


@app.post("/api/save")
def api_save():
    """บันทึกฟอร์มโดยไม่เชื่อมต่อ (เรียกแบบ debounce จากหน้าเว็บ)"""
    is_active, _, _ = license_manager.verify_license(cached_only=True)
    if not is_active:
        return jsonify(ok=False, error="โปรดเปิดใช้งาน License Key ก่อน"), 403
    form, show, ts, _ = parse_request()
    with lock:
        S.update(form=form, show_time=show, chosen_ts=ts)
        persist()
    return jsonify(ok=True)


def launch_app_window(url):
    time.sleep(1.0)
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            try:
                subprocess.Popen([p, f"--app={url}"])
                return
            except Exception:
                pass
    webbrowser.open(url)


def ensure_single_instance():
    """หากมีโปรเซสเก่ารันค้างอยู่บนพอร์ต 5000 ให้สั่งปิดโปรเซสเก่าก่อนเริ่มตัวใหม่"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((HOST, PORT)) == 0:
            try:
                req = urllib.request.Request(
                    f"http://{HOST}:{PORT}/api/shutdown",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=1.5)
            except Exception:
                pass
            time.sleep(0.8)


def run_app():
    # Fix working directory for PyInstaller frozen app
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    ensure_single_instance()
    threading.Thread(target=lambda: launch_app_window(f"http://{HOST}:{PORT}"), daemon=True).start()
    try:
        app.run(host=HOST, port=PORT, threaded=True, debug=False)
    finally:
        if S["worker"]:
            S["worker"].q.put(("stop", None))
            time.sleep(0.25)


if __name__ == "__main__":
    run_app()
