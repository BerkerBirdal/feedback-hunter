"""
license_check.py — Feedback Hunter giriş ekranı.
Açılışta fbhunter.berkerbirdal.com/api/auth ile doğrular.

Copyright (c) 2026 Berker Birdal. Tüm hakları saklıdır. / All Rights Reserved.
İzinsiz kopyalama, dağıtma ve değiştirme yasaktır. Bkz. LICENSE.
"""

import os, sys, json, time, hashlib, tempfile, subprocess, urllib.request, urllib.error
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


def _download_and_run_update(username, password, parent=None):
    """Yeni kurulum dosyasını auth'lu endpoint'ten indirip çalıştırır. Başarılıysa uygulamayı kapatır."""
    import tkinter.messagebox as mb
    plat = _platform_key()
    suffix = ".exe" if plat == "windows" else (".dmg" if plat == "macos" else ".bin")
    try:
        payload = json.dumps({"username": username, "password": password, "platform": plat}).encode()
        req = urllib.request.Request(
            SERVER_URL.rstrip("/") + "/api/download", data=payload,
            headers={"Content-Type": "application/json",
                     "User-Agent": f"FeedbackHunter/{APP_VERSION}"}, method="POST",
        )
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="FeedbackHunter-update-")
        with urllib.request.urlopen(req, timeout=120) as resp, os.fdopen(fd, "wb") as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
    except Exception as e:
        mb.showerror("Güncelleme Hatası",
                     f"Güncelleme indirilemedi:\n{e}\n\nDaha sonra tekrar deneyin.", parent=parent)
        return False

    # İndirilen kurulumu başlat
    try:
        if plat == "windows":
            os.startfile(path)                       # Inno Setup kurulumu açılır
        elif plat == "macos":
            subprocess.Popen(["open", path])         # DMG açılır
        else:
            mb.showinfo("Güncelleme", f"Kurulum indirildi:\n{path}", parent=parent)
            return False
    except Exception as e:
        mb.showerror("Güncelleme Hatası", f"Kurulum başlatılamadı:\n{e}", parent=parent)
        return False

    mb.showinfo("Güncelleme",
                "Güncelleme başlatıldı. Kurulumu tamamlayın; uygulama şimdi kapanacak.",
                parent=parent)
    raise SystemExit(0)


def maybe_offer_update(username, password, parent=None):
    """Giriş SONRASI: yeni sürüm varsa uygulama içinden güncelleme sunar (siteye gitmeden)."""
    data = _fetch_version_info()
    if not data:
        return
    latest = data.get("latest_version", APP_VERSION)
    if latest == APP_VERSION:
        return
    force = data.get("force_update", False)
    import tkinter.messagebox as mb
    if force:
        # Zorunlu: tek yol güncelleme; reddederse uygulama açılmaz
        yes = mb.askokcancel(
            "Güncelleme Zorunlu",
            f"Feedback Hunter v{latest} zorunlu güncellemedir.\n\n"
            f"'Tamam'a basınca güncelleme uygulama içinden indirilip kurulacak.",
            parent=parent)
        if not yes:
            raise SystemExit(0)
        _download_and_run_update(username, password, parent)
        raise SystemExit(0)   # indirme başarısızsa da zorunlu sürümle devam etme
    else:
        yes = mb.askyesno(
            "Yeni Sürüm Mevcut",
            f"Feedback Hunter v{latest} yayında (sende v{APP_VERSION}).\n\n"
            f"Şimdi güncellemek ister misin? (Uygulama içinden indirilir)",
            parent=parent)
        if yes:
            _download_and_run_update(username, password, parent)


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
    if not _check_remote_control():          # giriş öncesi: kill-switch
        raise SystemExit(0)
    dlg = LoginDialog()
    dlg.mainloop()
    if not dlg.result:
        raise SystemExit(0)
    _set_credentials(getattr(dlg, "username", ""), getattr(dlg, "password", ""))
    # giriş sonrası: yeni sürüm varsa uygulama içinden güncelleme sun (siteye gitmeden)
    try:
        maybe_offer_update(getattr(dlg, "username", ""), getattr(dlg, "password", ""))
    except SystemExit:
        raise
    except Exception:
        pass
