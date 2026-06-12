# Feedback Hunter — Build Talimatları

## Otomatik Build (GitHub Actions — ÖNERİLEN)

### 1. GitHub repo oluştur
```bash
cd ~/feedback_killer
git init
git add .
git commit -m "feat: Feedback Hunter v0.1"
# GitHub'da yeni repo aç, sonra:
git remote add origin https://github.com/KULLANICI_ADI/feedback-hunter.git
git push -u origin main
```

### 2. Tag ile build tetikle
```bash
git tag v0.1
git push origin v0.1
```

### 3. Artifact'leri indir
- GitHub → Actions → Build Feedback Hunter → son run
- `feedback_hunter_windows` → `FeedbackHunter.exe`
- `feedback_hunter_macos`   → `feedback_hunter_macos.dmg`

### 4. Sunucuya yükle
```bash
sshpass -p 'xYp0BSvCFw9h' scp -P 23422 FeedbackHunter.exe \
  root@136.144.232.48:/var/www/fbhunter.berkerbirdal.com/releases/feedback_hunter_windows_setup.exe

sshpass -p 'xYp0BSvCFw9h' scp -P 23422 feedback_hunter_macos.dmg \
  root@136.144.232.48:/var/www/fbhunter.berkerbirdal.com/releases/feedback_hunter_macos.dmg
```
İndirme sayfasında otomatik görünür.

## Manuel Build (macOS'ta — bu makine)
```bash
cd ~/feedback_killer
pip install pyinstaller sounddevice numpy scipy
pyinstaller feedback_hunter.spec
# dist/ altında "Feedback Hunter.app" oluşur
hdiutil create -volname "Feedback Hunter" \
  -srcfolder "dist/Feedback Hunter.app" \
  -ov -format UDZO feedback_hunter_macos.dmg
```

## Manuel Build (Windows VM gerektirir)
```cmd
pip install pyinstaller sounddevice numpy scipy
pyinstaller --onefile --windowed --name FeedbackHunter feedback_killer.py
# dist\FeedbackHunter.exe → yeniden adlandır: feedback_hunter_windows_setup.exe
```
