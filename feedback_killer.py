"""
Feedback Hunter v0.1 — Anti-Feedback / Anti-Reverb Aracı
=========================================================
Başlatılmadan önce license_check.require_login() çağrılır.
"""

from license_check import require_login
require_login()

import os, json, time, threading, datetime
import numpy as np
import scipy.signal as sig
import scipy.io.wavfile as wavfile
import sounddevice as sd
import tkinter as tk
from tkinter import ttk, messagebox

BLOCK_SIZE           = 1024
SAMPLE_RATE_DEFAULT  = 48000
BG_AVG_TIME_CONST    = 3.0
DETECT_RATIO_DB      = 6.0
PERSIST_FRAMES       = 4
MAX_NOTCHES_PER_CH   = 3
NOTCH_Q              = 25.0
RELEASE_FRAMES       = 30

RECORD_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
PROFILE_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venue_profile.json")

PROFILE_BUCKET_HZ        = 50.0
PROFILE_MAX_BONUS_DB     = 3.0
PROFILE_HITS_FOR_MAX_BONUS = 50


def load_venue_profile():
    try:
        with open(PROFILE_PATH) as f: return json.load(f)
    except Exception: return {}

def save_venue_profile(profile):
    try:
        with open(PROFILE_PATH, "w") as f: json.dump(profile, f, indent=2, sort_keys=True)
    except Exception: pass

def freq_bucket(freq):
    return str(int(round(freq / PROFILE_BUCKET_HZ) * PROFILE_BUCKET_HZ))


class ChannelProcessor:
    def __init__(self, samplerate, block_size, profile=None):
        self.fs, self.n = samplerate, block_size
        self.window  = np.hanning(self.n)
        self.profile = profile or {}
        self.bg_mag  = None
        self.alpha_bg = np.exp(-self.n / (self.fs * BG_AVG_TIME_CONST))
        self.candidates   = {}
        self.active_notches = {}
        self.notch_states   = {}
        self.last_detected_freqs = []
        n_bins = self.n // 2 + 1
        self.threshold_db = np.full(n_bins, DETECT_RATIO_DB)
        for b in range(n_bins):
            hits = self.profile.get(freq_bucket(self.freq_for_bin(b)), 0)
            if hits > 0:
                bonus = min(PROFILE_MAX_BONUS_DB, hits / PROFILE_HITS_FOR_MAX_BONUS * PROFILE_MAX_BONUS_DB)
                self.threshold_db[b] = DETECT_RATIO_DB - bonus

    def freq_for_bin(self, b): return b * self.fs / self.n

    def _design_notch_sos(self, freq):
        freq = max(20.0, min(freq, self.fs / 2 - 50))
        b, a = sig.iirnotch(freq / (self.fs / 2), NOTCH_Q)
        return sig.tf2sos(b, a)

    def process_block(self, x, wet):
        dry  = x.copy()
        spec = np.fft.rfft(x * self.window)
        mag  = np.abs(spec)
        if self.bg_mag is None: self.bg_mag = mag.copy() + 1e-6
        else: self.bg_mag = self.alpha_bg * self.bg_mag + (1 - self.alpha_bg) * mag
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio_db    = 20 * np.log10((mag + 1e-9) / (self.bg_mag + 1e-9))
            smooth      = np.convolve(mag, np.ones(7) / 7.0, mode="same")
            sharpness_db = 20 * np.log10((mag + 1e-9) / (smooth + 1e-9))
        candidate_bins = np.where((ratio_db > self.threshold_db) & (sharpness_db > 3.0))[0]
        new_cands = {}
        for b in candidate_bins: new_cands[int(b)] = self.candidates.get(int(b), 0) + 1
        self.candidates = new_cands
        for b, cnt in list(self.candidates.items()):
            if cnt >= PERSIST_FRAMES and b not in self.active_notches:
                if len(self.active_notches) < MAX_NOTCHES_PER_CH:
                    self.active_notches[b] = RELEASE_FRAMES
                    self.notch_states[b]   = None
                    bucket = freq_bucket(self.freq_for_bin(b))
                    self.profile[bucket] = self.profile.get(bucket, 0) + 1
        y = dry.copy()
        active_freqs = []
        for b, release in list(self.active_notches.items()):
            freq = self.freq_for_bin(b)
            active_freqs.append(round(freq, 1))
            sos = self._design_notch_sos(freq)
            if self.notch_states[b] is None:
                zi = sig.sosfilt_zi(sos)
                self.notch_states[b] = zi * y[0] if len(y) else zi
            y, self.notch_states[b] = sig.sosfilt(sos, y, zi=self.notch_states[b])
            if b not in self.candidates:
                release -= 1
                self.active_notches[b] = release
                if release <= 0:
                    del self.active_notches[b]; del self.notch_states[b]
            else:
                self.active_notches[b] = RELEASE_FRAMES
        self.last_detected_freqs = active_freqs
        return (1.0 - wet) * dry + wet * y, active_freqs


class AudioEngine:
    def __init__(self, in_device, out_device, channels_in_range, in_total, out_total, samplerate, status_cb):
        self.in_device  = in_device
        self.out_device = out_device
        self.start_ch, self.end_ch = channels_in_range
        self.n_channels = self.end_ch - self.start_ch + 1
        self.in_total   = in_total
        self.out_total  = out_total
        self.same_device = (in_device == out_device)
        self.fs         = samplerate
        self.status_cb  = status_cb
        self.wet        = 0.5
        self.recording_enabled = False
        self.input_level_db    = -100.0
        self.output_level_db   = -100.0
        self._rec_buffer = []; self._rec_freqs = set(); self._rec_active = False
        self.venue_profile = load_venue_profile()
        self.processors = [ChannelProcessor(self.fs, BLOCK_SIZE, profile=self.venue_profile)
                           for _ in range(self.n_channels)]
        self.stream = None
        self._lock  = threading.Lock()

    def get_venue_profile_summary(self):
        return len(self.venue_profile), sum(self.venue_profile.values())

    def get_level_db(self):
        with self._lock: return self.input_level_db
    def get_output_level_db(self):
        with self._lock: return self.output_level_db
    def set_wet(self, pct):
        with self._lock: self.wet = max(0.0, min(1.0, pct / 100.0))
    def set_recording(self, enabled):
        self.recording_enabled = enabled
        if enabled: os.makedirs(RECORD_DIR, exist_ok=True)

    def _maybe_record(self, raw_block, active_freqs):
        if not self.recording_enabled: return
        if active_freqs:
            self._rec_buffer.append(raw_block.copy())
            for _, f in active_freqs: self._rec_freqs.add(round(f))
            self._rec_active = True
        elif self._rec_active: self._flush_recording()

    def _flush_recording(self):
        if not self._rec_buffer: self._rec_active = False; return
        try:
            data = np.concatenate(self._rec_buffer, axis=0)
            ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fstr = "-".join(str(f) for f in sorted(self._rec_freqs))
            dur  = int(1000 * data.shape[0] / self.fs)
            fname = os.path.join(RECORD_DIR, f"feedback_{ts}_{fstr}Hz_{dur}ms.wav")
            os.makedirs(RECORD_DIR, exist_ok=True)
            wavfile.write(fname, self.fs, np.clip(data, -1.0, 1.0).astype(np.float32))
        except Exception: pass
        finally: self._rec_buffer = []; self._rec_freqs = set(); self._rec_active = False

    def _process(self, indata, wet):
        sel = indata[:, self.start_ch - 1:self.end_ch]
        rms = float(np.sqrt(np.mean(np.square(sel.astype(np.float64))) + 1e-12))
        with self._lock: self.input_level_db = 20.0 * np.log10(rms + 1e-12)
        if indata.shape[0] != BLOCK_SIZE: return sel, []
        processed = np.empty_like(sel)
        all_freqs = []
        for i in range(self.n_channels):
            y, freqs = self.processors[i].process_block(sel[:, i].astype(np.float64), wet)
            processed[:, i] = y.astype(np.float32)
            if freqs: all_freqs.extend([(i + self.start_ch, f) for f in freqs])
        out_rms = float(np.sqrt(np.mean(np.square(processed.astype(np.float64))) + 1e-12))
        with self._lock: self.output_level_db = 20.0 * np.log10(out_rms + 1e-12)
        self._maybe_record(sel.copy(), all_freqs)
        if self.status_cb: self.status_cb(all_freqs)
        return processed, all_freqs

    def _duplex_callback(self, indata, outdata, frames, time_info, status):
        with self._lock: wet = self.wet
        if self.same_device: outdata[:] = indata
        else: outdata[:] = 0.0
        if indata.shape[0] != BLOCK_SIZE: return
        processed, _ = self._process(indata, wet)
        if self.same_device: outdata[:, self.start_ch - 1:self.end_ch] = processed
        elif self.n_channels == self.out_total: outdata[:] = processed
        elif self.n_channels == 1: outdata[:] = np.repeat(processed, self.out_total, axis=1)
        else:
            m = min(self.n_channels, self.out_total)
            outdata[:, :m] = processed[:, :m]

    def _input_only_callback(self, indata, frames, time_info, status):
        with self._lock: wet = self.wet
        self._process(indata, wet)

    def start(self):
        if self.same_device:
            self.stream = sd.Stream(device=(self.in_device, self.out_device),
                samplerate=self.fs, blocksize=BLOCK_SIZE,
                channels=(self.in_total, self.out_total), dtype="float32",
                callback=self._duplex_callback)
        else:
            self.stream = sd.InputStream(device=self.in_device,
                samplerate=self.fs, blocksize=BLOCK_SIZE,
                channels=self.in_total, dtype="float32",
                callback=self._input_only_callback)
        self.stream.start()

    def stop(self):
        if self.stream: self.stream.stop(); self.stream.close(); self.stream = None
        if self._rec_active: self._flush_recording()
        save_venue_profile(self.venue_profile)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Feedback Hunter v0.1")
        self.geometry("560x600")
        self.minsize(560, 600)
        self.engine = self.in_device = self.out_device = None
        self.in_total = self.out_total = 0
        self.frame_device = DeviceFrame(self, self.on_device_chosen)
        self.frame_channels = self.frame_main = None
        self.frame_device.pack(fill="both", expand=True)

    def on_device_chosen(self, in_dev, out_dev, in_t, out_t):
        self.in_device = in_dev; self.out_device = out_dev
        self.in_total = in_t; self.out_total = out_t
        self.frame_device.pack_forget()
        self.frame_channels = ChannelFrame(self, in_t, self.on_channels_chosen, self._back_to_device)
        self.frame_channels.pack(fill="both", expand=True)

    def _back_to_device(self):
        self.frame_channels.pack_forget(); self.frame_channels = None
        self.frame_device.pack(fill="both", expand=True)

    def _back_from_main(self):
        if self.engine and self.frame_main and self.frame_main.running: self.engine.stop()
        if self.frame_main: self.frame_main.pack_forget(); self.frame_main = None
        self.engine = None
        self.frame_device = DeviceFrame(self, self.on_device_chosen)
        self.frame_device.pack(fill="both", expand=True)

    def on_channels_chosen(self, start, end):
        self.frame_channels.pack_forget()
        info = sd.query_devices(self.in_device)
        fs = int(info["default_samplerate"]) or SAMPLE_RATE_DEFAULT
        self.engine = AudioEngine(self.in_device, self.out_device, (start, end),
                                  self.in_total, self.out_total, fs, self.update_status)
        self.frame_main = MainFrame(self, self.engine)
        self.frame_main.pack(fill="both", expand=True)

    def update_status(self, freqs):
        if self.frame_main: self.frame_main.set_status(freqs)


class DeviceFrame(ttk.Frame):
    def __init__(self, master, on_chosen):
        super().__init__(master, padding=20)
        self.on_chosen = on_chosen
        ttk.Label(self, text="1) Ses Kartı Seçimi", font=("", 14, "bold")).pack(pady=(0, 5))
        self.in_devs  = self._list_devices(True)
        self.out_devs = self._list_devices(False)
        ttk.Label(self, text="Giriş cihazı:").pack(anchor="w", pady=(10, 0))
        self.in_cb = ttk.Combobox(self, values=[d[0] for d in self.in_devs], state="readonly", width=58)
        if self.in_devs: self.in_cb.current(0)
        self.in_cb.pack(pady=5)
        ttk.Label(self, text="Çıkış cihazı:").pack(anchor="w", pady=(10, 0))
        self.out_cb = ttk.Combobox(self, values=[d[0] for d in self.out_devs], state="readonly", width=58)
        def_idx = 0
        if self.in_devs:
            in_name = self.in_devs[self.in_cb.current()][0].split("  (")[0]
            for i, d in enumerate(self.out_devs):
                if d[0].startswith(in_name): def_idx = i; break
        if self.out_devs: self.out_cb.current(def_idx)
        self.out_cb.pack(pady=5)
        ttk.Button(self, text="Devam", command=self._go).pack(pady=15)
        if not self.in_devs or not self.out_devs:
            ttk.Label(self, text="Giriş veya çıkış cihazı bulunamadı.", foreground="red").pack()

    def _list_devices(self, inp):
        res = []
        try:
            for i, d in enumerate(sd.query_devices()):
                if inp and d["max_input_channels"] > 0:
                    res.append((f"{d['name']}  (in:{d['max_input_channels']})", i, d["max_input_channels"]))
                elif not inp and d["max_output_channels"] > 0:
                    res.append((f"{d['name']}  (out:{d['max_output_channels']})", i, d["max_output_channels"]))
        except Exception as e: messagebox.showerror("Hata", str(e))
        return res

    def _go(self):
        ii, oi = self.in_cb.current(), self.out_cb.current()
        if ii < 0 or oi < 0: messagebox.showwarning("Uyarı", "Cihaz seçin."); return
        _, id_, it = self.in_devs[ii]; _, od_, ot = self.out_devs[oi]
        self.on_chosen(id_, od_, it, ot)


class ChannelFrame(ttk.Frame):
    def __init__(self, master, max_ch, on_chosen, on_back):
        super().__init__(master, padding=20)
        self.on_chosen = on_chosen
        ttk.Label(self, text="2) Giriş Kanal Aralığı", font=("", 14, "bold")).pack(pady=(0, 10))
        ttk.Label(self, text=f"{max_ch} kanal mevcut. İşlenecek aralığı seçin:").pack(anchor="w")
        frm = ttk.Frame(self); frm.pack(pady=20)
        ttk.Label(frm, text="Başlangıç:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.start_var = tk.IntVar(value=1)
        ttk.Spinbox(frm, from_=1, to=max_ch, textvariable=self.start_var, width=6).grid(row=0, column=1, padx=5)
        ttk.Label(frm, text="Bitiş:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.end_var = tk.IntVar(value=min(2, max_ch))
        ttk.Spinbox(frm, from_=1, to=max_ch, textvariable=self.end_var, width=6).grid(row=1, column=1, padx=5)
        btns = ttk.Frame(self); btns.pack(pady=10)
        ttk.Button(btns, text="Geri", command=on_back).pack(side="left", padx=5)
        ttk.Button(btns, text="Devam", command=self._go).pack(side="left", padx=5)

    def _go(self):
        s, e = self.start_var.get(), self.end_var.get()
        if s > e or s < 1: messagebox.showwarning("Uyarı", "Geçersiz aralık."); return
        if (e - s + 1) > 8:
            if not messagebox.askyesno("Onay", f"{e-s+1} kanal işlenecek, CPU yorabilir. Devam?"): return
        self.on_chosen(s, e)


class MainFrame(ttk.Frame):
    def __init__(self, master, engine: AudioEngine):
        super().__init__(master, padding=20)
        self.engine  = engine
        self.running = False
        self.app     = master
        ttk.Label(self, text="3) Feedback Hunter", font=("", 14, "bold")).pack(pady=(0, 10))
        ttk.Label(self, text=f"Giriş: ch{engine.start_ch}-{engine.end_ch}/{engine.in_total}  "
                             f"Çıkış: {engine.out_total}ch  {engine.fs}Hz").pack()
        mode = ("Tam mod (işlenip gönderiliyor)" if engine.same_device
                else "İzleme modu (çıkışa ses gönderilmiyor)")
        ttk.Label(self, text=mode,
                  foreground=("black" if engine.same_device else "orange"),
                  wraplength=440, justify="center").pack(pady=(5, 0))
        nb, nh = engine.get_venue_profile_summary()
        self.profile_lbl = ttk.Label(self, text=f"Mekan Profili: {nb} frekans, {nh} tespit",
                                     foreground="gray", wraplength=460, justify="center")
        self.profile_lbl.pack(pady=(2, 0))

        ttk.Label(self, text="Giriş Seviyesi").pack(pady=(15, 0))
        self.level_bar = ttk.Progressbar(self, orient="horizontal", length=300, mode="determinate", maximum=100)
        self.level_bar.pack(pady=5)
        self.level_lbl = ttk.Label(self, text="-- dBFS"); self.level_lbl.pack()

        ttk.Label(self, text="Çıkış Seviyesi").pack(pady=(10, 0))
        self.out_bar = ttk.Progressbar(self, orient="horizontal", length=300, mode="determinate", maximum=100)
        self.out_bar.pack(pady=5)
        self.out_lbl = ttk.Label(self, text="-- dBFS"); self.out_lbl.pack()

        ttk.Label(self, text="Etki (Wet/Dry) %").pack(pady=(20, 0))
        self.wet_var = tk.DoubleVar(value=50.0)
        ttk.Scale(self, from_=0, to=100, orient="horizontal", variable=self.wet_var,
                  command=self._on_wet, length=300).pack(pady=5)
        self.wet_lbl = ttk.Label(self, text="50%"); self.wet_lbl.pack()

        self.rec_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Feedback anlarını kaydet", variable=self.rec_var,
                        command=lambda: engine.set_recording(self.rec_var.get())).pack(pady=10)

        self.start_btn = ttk.Button(self, text="BAŞLAT", command=self._toggle)
        self.start_btn.pack(pady=15)
        self.status_lbl = ttk.Label(self, text="Durum: Beklemede", wraplength=400, justify="center")
        self.status_lbl.pack(pady=10)
        ttk.Button(self, text="< Cihazları Değiştir", command=self.app._back_from_main).pack(pady=5)
        self._on_wet(self.wet_var.get())

    def _on_wet(self, val):
        v = float(val)
        self.wet_lbl.config(text=f"{v:.0f}%")
        if self.engine: self.engine.set_wet(v)

    def _toggle(self):
        if not self.running:
            try:
                self.engine.start(); self.running = True
                self.start_btn.config(text="DURDUR")
                self.status_lbl.config(text="Durum: Çalışıyor...")
                self._poll()
            except Exception as e: messagebox.showerror("Hata", str(e))
        else:
            self.engine.stop(); self.running = False
            self.start_btn.config(text="BAŞLAT")
            self.status_lbl.config(text="Durum: Durduruldu")
            for bar in (self.level_bar, self.out_bar): bar["value"] = 0
            for lbl in (self.level_lbl, self.out_lbl): lbl.config(text="-- dBFS")

    def _poll(self):
        if not self.running: return
        for db, bar, lbl in [(self.engine.get_level_db(), self.level_bar, self.level_lbl),
                              (self.engine.get_output_level_db(), self.out_bar, self.out_lbl)]:
            bar["value"] = max(0, min(100, (db + 60) / 60 * 100))
            lbl.config(text=f"{db:.1f} dBFS")
        nb, nh = self.engine.get_venue_profile_summary()
        self.profile_lbl.config(text=f"Mekan Profili: {nb} frekans, {nh} tespit")
        self.after(100, self._poll)

    def set_status(self, freqs):
        if not freqs: self.status_lbl.config(text="Durum: Çalışıyor... (feedback yok)")
        else:
            txt = ", ".join(f"Ch{ch}: {f:.0f}Hz" for ch, f in freqs)
            self.status_lbl.config(text=f"Aktif notch → {txt}")


if __name__ == "__main__":
    App().mainloop()
