"""
license_check.py — Feedback Hunter giriş ekranı.
Açılışta fbhunter.berkerbirdal.com/api/auth ile doğrular.

Copyright (c) 2026 Berker Birdal. Tüm hakları saklıdır. / All Rights Reserved.
İzinsiz kopyalama, dağıtma ve değiştirme yasaktır. Bkz. LICENSE.
"""

import os, json, time, hashlib, urllib.request, urllib.error
import tkinter as tk
from tkinter import ttk

SERVER_URL            = "https://fbhunter.berkerbirdal.com"
CACHE_PATH            = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fbhunter_auth")
OFFLINE_GRACE_SECONDS = 7 * 24 * 3600  # 7 gün
APP_VERSION           = "0.1.0"


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

def _check_remote_control():
    """Sunucudan kill switch ve versiyon kontrolü. False dönerse uygulama kapanmalı."""
    try:
        url = f"{SERVER_URL}/api/version?v={APP_VERSION}"
        req = urllib.request.Request(url, headers={"User-Agent": f"FeedbackHunter/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())

        if not data.get("active", True):
            msg = data.get("message") or "Bu yazılımın lisansı iptal edilmiştir.\n\nBilgi: bossproankara@gmail.com"
            import tkinter.messagebox as mb
            root = tk.Tk(); root.withdraw()
            mb.showerror("Feedback Hunter — Lisans İptal", msg)
            root.destroy()
            return False

        latest = data.get("latest_version", APP_VERSION)
        force  = data.get("force_update", True)   # varsayılan: sürüm farkı ZORUNLU güncelleme
        if latest != APP_VERSION:
            import tkinter.messagebox as mb
            root = tk.Tk(); root.withdraw()
            if force:
                mb.showwarning(
                    "Güncelleme Zorunlu",
                    f"Feedback Hunter v{latest} güncelleme zorunludur.\n"
                    f"Lütfen güncelleme yapın:\n{data.get('download_url', SERVER_URL)}"
                )
                root.destroy()
                return False
            else:
                mb.showinfo(
                    "Yeni Sürüm Mevcut",
                    f"Feedback Hunter v{latest} yayında!\n"
                    f"Güncellemek için: {data.get('download_url', SERVER_URL)}"
                )
            root.destroy()

    except Exception:
        pass  # Sunucuya ulaşılamazsa devam et (offline kullanım)

    return True


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
                self.result = True; self.destroy(); return
            self.status_lbl.config(text="Sunucuya ulaşılamıyor ve önbellek bulunamadı. "
                                        "İlk girişte internet gerekli.")
            return
        if status == "approved":
            _save_cache(u, p); self.result = True; self.destroy()
        elif status == "pending":
            self.status_lbl.config(text="Hesabınız admin onayı bekliyor.")
        elif status == "rejected":
            self.status_lbl.config(text="Hesabınız reddedildi.")
        else:
            self.status_lbl.config(text="Kullanıcı adı veya şifre hatalı.")


def require_login():
    if not _check_remote_control():
        raise SystemExit(0)
    dlg = LoginDialog()
    dlg.mainloop()
    if not dlg.result:
        raise SystemExit(0)
