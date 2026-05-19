# flask_downloader

Panel Flask do ekstrakcji źródeł przez `yt-dlp`, kolejkowania pobrań na serwer, zarządzania lokalnymi plikami, obsługi biblioteki DLNA opartej o `Gerbera` oraz prywatnych stacji radiowych opartych o `Icecast` i `Liquidsoap`.

## Najważniejsze cechy
- UI i komunikaty po polsku
- rozdzielone role `admin` / `user`
- kolejka pobrań audio i wideo
- lokalnie zarządzany `ffmpeg` dla `yt-dlp`
- panel utrzymania `yt-dlp`, `ffmpeg` i `DLNA`
- moduł `Radio` z `Icecast`, `Liquidsoap`, AutoDJ i `eRDS`
- AJAXowa nawigacja i odświeżanie stanu bez pełnych reloadów
- biblioteka DLNA z bukietami, whitelistą IP i automatycznym sprzątaniem martwych wpisów

## Struktura projektu
```text
app.py
flask_downloader/
  config.py
  legacy_app.py
  paths.py
  routes/
  stores/
  utils/
templates/
static/
data/
scripts/
deploy/
```

## Dane i sekrety
Prawdziwe dane aplikacji nie powinny trafiać do repozytorium.

Katalog `data/` w środowisku roboczym zawiera:
- `data/config.json`
- `data/jobs.json`
- `data/users.json`
- `data/radios.json`

Do repo trafiają tylko przykłady:
- `data/config.example.json`
- `data/jobs.example.json`
- `data/users.example.json`
- `data/radios.example.json`

Sekrety i ustawienia środowiskowe trzymaj w lokalnym `.env`. W repo jest tylko `.env.example`.

## Szybki start lokalny
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Windows PowerShell:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

## Instalacja na Debianie
Docelowy instalator jest w:
- `scripts/install.sh`

Przykład:
```bash
sudo bash scripts/install.sh
```

Przykład nieinteraktywny:
```bash
export FLASK_DOWNLOADER_ADMIN_PASSWORD='TwojeHasloAdmina'
sudo bash scripts/install.sh \
  --non-interactive \
  --repo-url https://github.com/Q-Tronic/flask_downloader.git \
  --branch main \
  --app-dir /opt/flask_downloader \
  --storage-root /srv/flask_downloader/share \
  --user flaskdl \
  --group flaskdl \
  --port 9999
```

Docelowo po publikacji repo można odpalić także jednym poleceniem po SSH:
```bash
curl -fsSL https://raw.githubusercontent.com/Q-Tronic/flask_downloader/main/scripts/install.sh | sudo bash
```

Instalator:
- wykrywa Debiana 10+
- pyta o port aplikacji z timeoutem 30 sekund i domyślnym `9999`
- waliduje zakres portu i pilnuje konfliktów
- tworzy użytkownika Linux dla usługi
- tworzy `.env`
- tworzy pierwszego administratora aplikacji
- generuje losowy `FLASK_SECRET_KEY` oraz losowe hasła backendu radia przy pierwszym `data/radios.json`
- honoruje też własne nazwy usług `systemd` podane przez env lub parametry CLI, więc można bezpiecznie stawiać osobne instancje testowe
- aktualizuje `yt-dlp` w środowisku aplikacji
- instaluje zarządzany `ffmpeg` z `yt-dlp/FFmpeg-Builds`
- instaluje `Gerbera` i przygotowuje runtime DLNA
- instaluje `Icecast` i `Liquidsoap` dla modułu `Radio`
- doinstalowuje systemowe zależności używane przez aplikację, m.in. `cifs-utils`, `iproute2` i `ffmpegthumbnailer`
- nie nadpisuje istniejących danych w `data/`
- przy reinstalacji zostawia istniejące `.env` i `data/*.json`
- zapisuje szczegółowy log instalacji domyślnie do `/tmp/flask_downloader_install.log`

## Aktualizacja / deploy
Skrypty pomocnicze:
- `scripts/deploy.sh` dla systemów Unix-like
- `scripts/deploy.ps1` dla PowerShell / Windows

Oba skrypty:
- robią backup kodu na serwerze
- nie naruszają `data/`
- nie powinny nadpisywać `.env`
- restartują usługę aplikacji po wdrożeniu

## Porządkowanie legacy JSON po migracji
Po potwierdzonej migracji na `data/` możesz zarchiwizować stare rootowe pliki:
- `flask_downloader_config.json`
- `flask_downloader_jobs.json`
- `flask_downloader_users.json`

Suchy podgląd:
```bash
python3 scripts/cleanup_legacy_data.py --project-root /opt/flask_downloader --dry-run
```

Właściwe archiwizowanie do `backups/legacy-data-YYYYmmdd-HHMMSS`:
```bash
python3 scripts/cleanup_legacy_data.py --project-root /opt/flask_downloader
```

## GitHub
Przed publikacją dopilnuj:
- `.env` nie trafia do repo
- `data/*.json` z realnymi danymi nie trafiają do repo
- `data/runtime/` i `tools/ffmpeg/` nie trafiają do repo
- logi, runtime DLNA i lokalne cache nie trafiają do repo
- przykładowe JSON-y mają zawierać tylko jawne placeholdery, nigdy prawdziwe hasła live/source/admin

## Uwaga o DLNA
Serwer DLNA jest zarządzany z panelu administratora. Nowsze wersje `Gerbera` są preferowane, bo poprawnie obsługują logiczny układ `bukiet -> pliki` i izolację klientów.
