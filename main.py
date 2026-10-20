from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ai import advise, call_ai, chat_reply
from config import CONFIG_PATH, DB_PATH, load_config, save_config
from db import Database
from parser import parse


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
UI = ROOT / "ui"
db = Database(DB_PATH)
config = load_config()
DESKTOP_PET = False
MAIN_WINDOW = None
PET_WINDOW = None
TRAY_ICON = None
SHUTDOWN_REQUESTED = False
PET_VISIBLE = True
PENDING_CAPTURE = None


class DesktopPetApi:
    """Small native bridge for moving, focusing, and pasting into the floating assistant."""
    def get_position(self):
        try:
            return {"x": int(PET_WINDOW.x), "y": int(PET_WINDOW.y)} if PET_WINDOW else {"x": 0, "y": 0}
        except Exception:
            return {"x": 0, "y": 0}

    def move_window(self, x, y):
        try:
            if PET_WINDOW:
                PET_WINDOW.move(int(x), int(y))
        except Exception:
            pass

    def focus_window(self):
        try:
            if PET_WINDOW:
                PET_WINDOW.show()
                focus = getattr(PET_WINDOW, "focus", None)
                if callable(focus):
                    focus()
        except Exception:
            pass

    def read_clipboard(self):
        """Read plain text from the Windows clipboard for reliable Ctrl+V in the frameless pet."""
        if sys.platform.startswith("win"):
            try:
                import ctypes
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                user32.OpenClipboard.argtypes = [ctypes.c_void_p]
                user32.OpenClipboard.restype = ctypes.c_bool
                user32.GetClipboardData.argtypes = [ctypes.c_uint]
                user32.GetClipboardData.restype = ctypes.c_void_p
                kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
                kernel32.GlobalLock.restype = ctypes.c_void_p
                kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
                if not user32.OpenClipboard(0):
                    return ""
                try:
                    handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
                    if not handle:
                        return ""
                    ptr = kernel32.GlobalLock(handle)
                    if not ptr:
                        return ""
                    try:
                        return ctypes.wstring_at(ptr)
                    finally:
                        kernel32.GlobalUnlock(handle)
                finally:
                    user32.CloseClipboard()
            except Exception:
                return ""
        return ""


def public_config(data: dict):
    out = {k: v for k, v in data.items() if k not in ("providers", "api_key")}
    out["api_key"] = bool(data.get("api_key"))
    out["providers"] = [{k: v for k, v in p.items() if k != "api_key"} | {"api_key": bool(p.get("api_key"))} for p in data.get("providers", [])]
    out["desktop_pet"] = DESKTOP_PET
    out["desktop_pet_visible"] = PET_VISIBLE
    return out


def shutdown_desktop():
    """Close both desktop windows and stop the local server when the tray asks to quit."""
    global SHUTDOWN_REQUESTED
    SHUTDOWN_REQUESTED = True
    for window in (PET_WINDOW, MAIN_WINDOW):
        try:
            if window:
                window.destroy()
        except Exception:
            pass


def set_pet_visibility(visible: bool):
    global PET_VISIBLE
    PET_VISIBLE = bool(visible)
    try:
        if PET_WINDOW:
            PET_WINDOW.show() if PET_VISIBLE else PET_WINDOW.hide()
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store, no-cache, must-revalidate"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0)); return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state": return self._json({"tasks": db.tasks(True), "boards": db.boards(), "projects": db.projects(), "project_summaries": db.project_summaries(), "workstreams": db.workstreams(), "cards": db.cards(), "config": {**public_config(config), "config_path": str(CONFIG_PATH), "db_path": str(DB_PATH)}})
        if path == "/api/desktop/pending":
            global PENDING_CAPTURE
            pending = PENDING_CAPTURE or {}
            PENDING_CAPTURE = None
            return self._json(pending)
        if path == "/api/projects": return self._json({"projects": db.project_summaries()})
        if path == "/": path = "/index.html"
        file = (ROOT / path.lstrip("/")) if path.startswith("/assets/") else (UI / path.lstrip("/"))
        if file.exists() and file.is_file():
            data = file.read_bytes(); mime={".html":"text/html; charset=utf-8",".css":"text/css; charset=utf-8",".js":"application/javascript; charset=utf-8",".svg":"image/svg+xml",".png":"image/png",".ico":"image/x-icon"}.get(file.suffix,"application/octet-stream"); self.send_response(200); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        global config
        path = urlparse(self.path).path; payload = self._body()
        if path == "/api/parse":
            items, mode = call_ai(payload.get("text", ""), config, db.project_summaries()); return self._json({"items": items, "mode": mode})
        if path == "/api/tasks": return self._json({"task": db.add_task(payload)})
        if path.startswith("/api/tasks/"):
            tid = path.split("/")[-1]; db.update_task(tid, payload); return self._json({"ok": True})
        if path == "/api/advise": return self._json({"answer": advise(payload.get("question", ""), db.tasks(False), config)})
        if path == "/api/chat": return self._json({"answer": chat_reply(payload.get("question", ""), payload.get("history", []), db.tasks(False), config, db.project_summaries())})
        if path == "/api/pet-tip":
            prompt = "请根据当前任务和课题，只给我一句不超过45个汉字的轻松提醒或鼓励。每次换一个角度，可以提醒组会、截止日期、课题推进或下一步动作，不要列表，不要解释。"
            return self._json({"answer": chat_reply(prompt, [], db.tasks(False), config, db.project_summaries())})
        if path == "/api/pet-capture":
            text = str(payload.get("text", "")).strip()
            if not text:
                return self._json({"ok": False, "error": "请先输入要记录的内容"}, 400)
            items, mode = call_ai(text, config, db.project_summaries())
            return self._json({"ok": True, "mode": mode, "count": len(items), "items": items})
        if path == "/api/pet-confirm":
            items = payload.get("items") or []
            saved = [db.add_task(item) for item in items if isinstance(item, dict) and str(item.get("title", "")).strip()]
            return self._json({"ok": True, "count": len(saved), "tasks": saved})
        if path == "/api/desktop/quit":
            shutdown_desktop(); return self._json({"ok": True})
        if path == "/api/desktop/hide":
            set_pet_visibility(False); return self._json({"ok": True})
        if path == "/api/desktop/show":
            set_pet_visibility(True); return self._json({"ok": True})
        if path == "/api/desktop/pending" and payload:
            global PENDING_CAPTURE
            PENDING_CAPTURE = {"items": payload.get("items") or [], "mode": payload.get("mode", "offline"), "text": payload.get("text", "")}
            return self._json({"ok": True})
        if path == "/api/desktop/pending":
            pending = PENDING_CAPTURE or {}
            PENDING_CAPTURE = None
            return self._json(pending)
        if path == "/api/desktop/show-main":
            set_pet_visibility(True)
            try:
                if MAIN_WINDOW:
                    MAIN_WINDOW.show(); MAIN_WINDOW.restore()
            except Exception:
                pass
            return self._json({"ok": True})
        if path == "/api/ai/test":
            provider = payload.get("provider", {})
            stored_provider = next((p for p in config.get("providers", []) if p.get("id") == provider.get("id")), {})
            key = provider.get("api_key") if isinstance(provider.get("api_key"), str) else ""
            key = key or stored_provider.get("api_key", "") or (config.get("api_key") if provider.get("id") == config.get("active_provider_id") else "")
            if not key: return self._json({"ok": False, "error": "请先填写 API Key"}, 400)
            started = time.perf_counter()
            body = json.dumps({"model": provider.get("model", "deepseek-chat"), "messages": [{"role": "user", "content": "Reply with OK."}], "temperature": 0}).encode()
            req = urllib.request.Request(provider.get("base_url", "https://api.deepseek.com").rstrip("/") + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=8) as response:
                    json.loads(response.read().decode())
                return self._json({"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000)})
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)[:180]}, 400)
        if path == "/api/config":
            config = save_config(payload); return self._json({"ok": True, "config": public_config(config)})
        if path == "/api/boards": return self._json({"board": db.add_board(payload.get("name", "新模块"), payload.get("color", "#7A8FB8"))})
        if path.startswith("/api/boards/"):
            board_id = path.split("/")[-1]
            if payload.get("action") == "archive": db.archive_board(board_id)
            else: db.update_board(board_id, payload)
            return self._json({"ok": True})
        if path == "/api/projects": return self._json({"project": db.add_project(payload)})
        if path.startswith("/api/projects/"):
            project_id = path.split("/")[-1]
            if payload.get("action") == "delete":
                db.delete_project(project_id); return self._json({"ok": True, "deleted": project_id})
            if payload.get("action") == "archive": payload = {"status": "archived"}
            db.update_project(project_id, payload); return self._json({"ok": True})
        if path == "/api/workstreams": return self._json({"workstream": db.add_workstream(payload.get("project_id"), payload)})
        if path.startswith("/api/workstreams/"):
            stream_id = path.split("/")[-1]; db.update_workstream(stream_id, payload); return self._json({"ok": True})
        if path == "/api/cards": return self._json({"card": db.add_card(payload)})
        if path.startswith("/api/cards/"):
            card_id = path.split("/")[-1]
            if payload.get("action") == "delete": db.delete_card(card_id)
            else: db.update_card(card_id, payload)
            return self._json({"ok": True})
        if path == "/api/import": db.import_json(payload); return self._json({"ok": True})
        if path == "/api/export": return self._json(db.export_json())
        self._json({"error": "not found"}, 404)


def start_hotkey(url):
    try:
        import keyboard
        keyboard.add_hotkey("ctrl+alt+space", lambda: webbrowser.open(url + "#quick"))
    except Exception:
        pass


def start_tray():
    """Keep the floating assistant useful after the main window is hidden."""
    global TRAY_ICON
    try:
        import pystray
        from PIL import Image

        icon_path = ROOT / "assets" / "sciplan_icon.png"
        image = Image.open(icon_path) if icon_path.exists() else Image.new("RGBA", (64, 64), "#24344f")

        def open_main(icon, item):
            try:
                if MAIN_WINDOW:
                    MAIN_WINDOW.show(); MAIN_WINDOW.restore()
            except Exception:
                pass

        def toggle_pet(icon, item):
            global PET_VISIBLE
            try:
                if PET_WINDOW:
                    set_pet_visibility(not PET_VISIBLE)
            except Exception:
                pass

        def quit_app(icon, item):
            shutdown_desktop()
            try: icon.stop()
            except Exception: pass

        TRAY_ICON = pystray.Icon("SciPlan", image, "SciPlan 科研计划", pystray.Menu(
            pystray.MenuItem("打开 SciPlan", open_main, default=True),
            pystray.MenuItem("显示 / 隐藏桌面助手", toggle_pet),
            pystray.MenuItem("退出 SciPlan", quit_app),
        ))
        TRAY_ICON.run()
    except Exception:
        # A missing tray backend should not prevent the main application from opening.
        return


def main():
    global DESKTOP_PET, MAIN_WINDOW, PET_WINDOW
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    start_hotkey(url)
    print(f"ResearchFlow running at {url}", flush=True)
    try:
        import webview
        DESKTOP_PET = True
        MAIN_WINDOW = webview.create_window("SciPlan · 科研计划", url, width=1200, height=760, min_size=(900, 620), resizable=True, confirm_close=False)
        pet_size = max(72, min(160, int(config.get("pet_size", 92) or 92)))
        pet_width, pet_height = 360, 300
        try:
            import ctypes
            screen_width = ctypes.windll.user32.GetSystemMetrics(0)
            screen_height = ctypes.windll.user32.GetSystemMetrics(1)
            pet_x = max(0, screen_width - pet_width - 28)
            pet_y = max(0, screen_height - pet_height - 72)
        except Exception:
            pet_x = pet_y = None
        PET_WINDOW = webview.create_window("SciPlan 小助手", url + "/pet.html", width=pet_width, height=pet_height, x=pet_x, y=pet_y, min_size=(pet_width, pet_height), resizable=False, frameless=True, transparent=True, on_top=True, easy_drag=False, focus=True, shadow=False, background_color="#000000", js_api=DesktopPetApi())

        def keep_pet_on_main_hide(window=None):
            try:
                if PET_WINDOW and PET_VISIBLE: PET_WINDOW.show()
            except Exception: pass

        def hide_instead_of_quit(window=None):
            if SHUTDOWN_REQUESTED: return True
            try:
                if MAIN_WINDOW: MAIN_WINDOW.hide()
                if PET_WINDOW and PET_VISIBLE: PET_WINDOW.show()
            except Exception: pass
            return False

        MAIN_WINDOW.events.minimized += keep_pet_on_main_hide
        MAIN_WINDOW.events.closing += hide_instead_of_quit
        threading.Thread(target=start_tray, daemon=True).start()
        webview.start()
    except Exception:
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()


if __name__ == "__main__": main()
