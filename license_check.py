"""
license_check.py — Feedback Hunter giriş ekranı.
Açılışta fbhunter.berkerbirdal.com/api/auth ile doğrular.

Copyright (c) 2026 Berker Birdal. Tüm hakları saklıdır. / All Rights Reserved.
İzinsiz kopyalama, dağıtma ve değiştirme yasaktır. Bkz. LICENSE.
"""

import os, sys, json, time, hashlib, tempfile, threading, subprocess, urllib.request, urllib.error
import tkinter as tk
from tkinter import ttk

SERVER_URL            = "https://fbhunter.berkerbirdal.com"
CACHE_PATH            = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fbhunter_auth")
OFFLINE_GRACE_SECONDS = 7 * 24 * 3600  # 7 gün
APP_VERSION           = "0.1.0"


_CREDS = {"u": "", "p": ""}

def get_credentials():
    """Giriş sonrası kimlik (bulut katkısı için). ('', '') = giriş yok."""
    return _CREDS["u"], _CREDS["p"]

def _set_credentials(u, p):
    _CREDS["u"] = u or ""; _CREDS["p"] = p or ""


def _cache_key(username, password):
    return hashlib.sha256(f"{username}:{password}".encode()).hexdigest()

def _load_cache():
    try:
        with open(CACHE_PATH) as f: return json.load(f)
    except Exception: return None

def _save_cache(username, password):
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump({"key": _cache_key(username, password), "ts": time.time()}, f)
    except Exception: pass

def _check_cache(username, password):
    data = _load_cache()
    if not data: return False
    if data.get("key") != _cache_key(username, password): return False
    return (time.time() - data.get("ts", 0)) < OFFLINE_GRACE_SECONDS

def _fetch_version_info():
    """Sunucudan sürüm/kill-switch bilgisini çeker. Dict veya None döner."""
    try:
        url = f"{SERVER_URL}/api/version?v={APP_VERSION}"
        req = urllib.request.Request(url, headers={"User-Agent": f"FeedbackHunter/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None  # offline: çağıran taraf devam etsin


def _check_remote_control():
    """Kill switch kontrolü (giriş ÖNCESİ, kimlik gerektirmez). False dönerse uygulama kapanmalı."""
    data = _fetch_version_info()
    if not data:
        return True  # sunucuya ulaşılamazsa offline kullanıma izin ver
    if not data.get("active", True):
        msg = data.get("message") or "Bu yazılımın lisansı iptal edilmiştir.\n\nBilgi: bossproankara@gmail.com"
        import tkinter.messagebox as mb
        root = tk.Tk(); root.withdraw()
        mb.showerror("Feedback Hunter — Lisans İptal", msg)
        root.destroy()
        return False
    return True


def _platform_key():
    return "windows" if sys.platform.startswith("win") else ("macos" if sys.platform == "darwin" else "other")


def _download_installer(url, dest, progress_cb=None):
    """Kurulum dosyasını indirir; progress_cb(indirilen, toplam) ile ilerleme bildirir."""
    req = urllib.request.Request(url, headers={"User-Agent": f"FeedbackHunter/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as out:
            while True:
                chunk = resp.read(131072)
                if not chunk:
                    break
                out.write(chunk); done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)


class UpdaterScreen(tk.Tk):
    """Açılış sürüm-kontrol + otomatik güncelleme ekranı (LOGIN'DEN ÖNCE).
    Güncel değilse burada görünür ilerleme çubuğuyla indirir, kurulumu başlatır ve kapanır.
    result: 'proceed' (login'e geç) | 'exit' (uygulamayı kapat)."""
    def __init__(self):
        super().__init__()
        self.title("Feedback Hunter")
        self.geometry("430x220")
        self.resizable(False, False)
        self.result = None
        self._pct = 0.0
        self._dl = None
        self._status = "Sürüm kontrol ediliyor…"
        self._phase = "checking"   # checking | updating | done_proceed | done_exit | error

        ttk.Label(self, text="Feedback Hunter", font=("", 15, "bold")).pack(pady=(26, 2))
        ttk.Label(self, text="Otomatik Geri Besleme Avcısı",
                  foreground="gray", font=("", 9)).pack()
        self.status_lbl = ttk.Label(self, text=self._status, wraplength=380, justify="center")
        self.status_lbl.pack(pady=(16, 10))
        self.pbar = ttk.Progressbar(self, orient="horizontal", length=340, mode="indeterminate")
        self.pbar.pack(pady=(0, 6)); self.pbar.start(12)
        self.sub_lbl = ttk.Label(self, text="", foreground="gray", font=("", 9))
        self.sub_lbl.pack()

        threading.Thread(target=self._worker, daemon=True).start()
        self.after(120, self._poll)

    def _worker(self):
        data = _fetch_version_info()
        if not data:
            self._phase = "done_proceed"; return          # offline → login'e geç (offline grace)
        if not data.get("active", True):
            self._status = data.get("message") or \
                "Bu yazılımın lisansı iptal edilmiştir.\nBilgi: bossproankara@gmail.com"
            self._phase = "error"; return                 # kill switch
        latest = data.get("latest_version", APP_VERSION)
        if latest == APP_VERSION:
            self._phase = "done_proceed"; return          # güncel → login
        # --- güncelleme var: indir + kur ---
        self._status = f"Yeni sürüm v{latest} bulundu. İndiriliyor…"
        self._phase = "updating"
        plat = _platform_key()
        suffix = ".exe" if plat == "windows" else (".dmg" if plat == "macos" else ".bin")
        try:
            fd, path = tempfile.mkstemp(suffix=suffix, prefix="FeedbackHunter-update-")
            os.close(fd)
            url = SERVER_URL.rstrip("/") + f"/api/update-download?platform={plat}"
            def cb(done, total):
                self._pct = (done / total * 100.0) if total else 0.0
                self._dl = (done, total)
            _download_installer(url, path, cb)
        except Exception as e:
            self._status = f"Güncelleme indirilemedi:\n{e}\nLütfen internet bağlantınızı kontrol edin."
            self._phase = "error"; return
        try:
            if plat == "windows":
                os.startfile(path)
            elif plat == "macos":
                subprocess.Popen(["open", path])
        except Exception as e:
            self._status = f"Kurulum başlatılamadı:\n{e}"
            self._phase = "error"; return
        self._status = "Güncelleme kuruluyor… Kurulumu tamamlayın; bu pencere kapanacak."
        self._phase = "done_exit"

    def _poll(self):
        self.status_lbl.config(text=self._status)
        if self._phase == "updating":
            if self.pbar["mode"] != "determinate":
                self.pbar.stop(); self.pbar.config(mode="determinate", maximum=100)
            self.pbar["value"] = self._pct
            if self._dl and self._dl[1]:
                mb_done = self._dl[0] // (1024 * 1024); mb_tot = self._dl[1] // (1024 * 1024)
                self.sub_lbl.config(text=f"%{self._pct:.0f}   ({mb_done} / {mb_tot} MB)")
        if self._phase in ("checking", "updating"):
            self.after(150, self._poll); return
        # terminal durumlar
        self.pbar.stop()
        if self._phase == "done_proceed":
            self.result = "proceed"; self.destroy(); return
        if self._phase == "done_exit":
            self.sub_lbl.config(text="")
            self.after(1600, lambda: (setattr(self, "result", "exit"), self.destroy()))
            return
        # error
        self.pbar.pack_forget(); self.sub_lbl.pack_forget()
        ttk.Button(self, text="Kapat",
                   command=lambda: (setattr(self, "result", "exit"), self.destroy())).pack(pady=10)


def run_updater():
    """Açılış güncelleyicisini çalıştırır. 'proceed' → login; aksi halde uygulama kapanır."""
    scr = UpdaterScreen()
    scr.mainloop()
    return scr.result or "exit"


def _verify_online(username, password):
    try:
        payload = json.dumps({"username": username, "password": password}).encode()
        req = urllib.request.Request(
            SERVER_URL.rstrip("/") + "/api/auth", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            return json.loads(resp.read()).get("status", "invalid")
    except urllib.error.HTTPError as e:
        return "invalid" if e.code == 401 else "offline"
    except Exception:
        return "offline"


class LoginDialog(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Feedback Hunter - Giriş")
        self.geometry("380x260")
        self.resizable(False, False)
        self.result = False

        ttk.Label(self, text="Feedback Hunter",
                  font=("", 13, "bold")).pack(pady=(18, 2))
        ttk.Label(self, text="fbhunter.berkerbirdal.com hesabınızla giriş yapın",
                  wraplength=340, justify="center", foreground="gray").pack(pady=(0, 10))

        frm = ttk.Frame(self)
        frm.pack(pady=5)

        ttk.Label(frm, text="Kullanıcı adı:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.user_var = tk.StringVar()
        e = ttk.Entry(frm, textvariable=self.user_var, width=24)
        e.grid(row=0, column=1, padx=5)
        e.focus_set()

        ttk.Label(frm, text="Şifre:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.pass_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.pass_var, show="*", width=24).grid(row=1, column=1, padx=5)

        ttk.Button(self, text="Giriş Yap", command=self._submit).pack(pady=8)

        self.status_lbl = ttk.Label(self, text="", foreground="red",
                                    wraplength=340, justify="center")
        self.status_lbl.pack()

        ttk.Label(self, text="© 2026 Berker Birdal — Tüm hakları saklıdır",
                  font=("", 8), foreground="gray").pack(side="bottom", pady=(0, 6))
        self.bind("<Return>", lambda e: self._submit())

    def _submit(self):
        u, p = self.user_var.get().strip(), self.pass_var.get()
        if not u or not p:
            self.status_lbl.config(text="Kullanıcı adı ve şifre gerekli.")
            return
        self.status_lbl.config(text="Kontrol ediliyor...")
        self.update_idletasks()
        status = _verify_online(u, p)
        if status == "offline":
            if _check_cache(u, p):
                self.username = u; self.password = p
                self.result = True; self.destroy(); return
            self.status_lbl.config(text="Sunucuya ulaşılamıyor ve önbellek bulunamadı. "
                                        "İlk girişte internet gerekli.")
            return
        if status == "approved":
            _save_cache(u, p)
            self.username = u; self.password = p
            self.result = True; self.destroy()
        elif status == "pending":
            self.status_lbl.config(text="Hesabınız admin onayı bekliyor.")
        elif status == "rejected":
            self.status_lbl.config(text="Hesabınız reddedildi.")
        else:
            self.status_lbl.config(text="Kullanıcı adı veya şifre hatalı.")


def require_login():
    # 1) Açılış: sürüm kontrol + (güncel değilse) görünük ilerlemeli güncelleme — LOGIN'DEN ÖNCE.
    #    Kill-switch de burada kontrol edilir. 'proceed' değilse uygulama kapanır.
    if run_updater() != "proceed":
        raise SystemExit(0)
    # 2) Giriş ekranı
    dlg = LoginDialog()
    dlg.mainloop()
    if not dlg.result:
        raise SystemExit(0)
    _set_credentials(getattr(dlg, "username", ""), getattr(dlg, "password", ""))
