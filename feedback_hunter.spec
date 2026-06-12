# PyInstaller spec — her platformda kullanılır
# Windows:  pyinstaller feedback_hunter.spec
# macOS:    pyinstaller feedback_hunter.spec

block_cipher = None

a = Analysis(
    ['feedback_killer.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['sounddevice', 'scipy.signal', 'scipy.io.wavfile', 'numpy'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    [],
    name='FeedbackHunter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# macOS .app
app = BUNDLE(
    exe,
    name='Feedback Hunter.app',
    icon=None,
    bundle_identifier='com.berkerbirdal.feedbackhunter',
    info_plist={
        'NSMicrophoneUsageDescription': 'Feedback Hunter ses girişine erişim gerektirir.',
        'CFBundleShortVersionString': '0.1',
    },
)
