# VLC Stream Extractor

Panel WWW w `Flask` do:
- pobierania materiałów przez `yt-dlp`,
- zapisywania plików na serwerze,
- przeglądania własnych plików audio i wideo,
- zarządzania serwerem `DLNA`,
- tworzenia własnych stacji radiowych `Icecast + Liquidsoap`.

Interfejs i komunikaty są po polsku.

## Wymagania
- Debian 10 lub nowszy
- dostęp `root` lub `sudo`
- połączenie z internetem podczas instalacji

## Instalacja jednym poleceniem
Jeśli jesteś zalogowany jako `root`:
```bash
apt-get update && apt-get install -y curl ca-certificates && bash -c "$(curl -fsSL https://raw.githubusercontent.com/Q-Tronic/flask_downloader/main/scripts/install.sh)"
```

Jeśli używasz zwykłego konta z `sudo`:
```bash
sudo apt-get update && sudo apt-get install -y curl ca-certificates && sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/Q-Tronic/flask_downloader/main/scripts/install.sh)"
```

Instalator:
- pyta o port aplikacji,
- pyta o hasło pierwszego konta `admin`,
- pozwala zostawić domyślne ścieżki, użytkownika usługi i nazwy usług przez zwykłe `Enter`,
- przy nieudanej instalacji może usunąć pliki i usługi utworzone przez instalator, bez ruszania pakietów systemowych,
- startuje domyślnie na lokalnym serwerze danych, więc panel działa od razu po instalacji bez udziału sieciowego,
- tworzy usługę `systemd`,
- instaluje `yt-dlp`,
- instaluje zarządzany `ffmpeg`,
- instaluje backend `DLNA` oparty o `Gerbera`,
- instaluje backend radia oparty o `Icecast` i `Liquidsoap`,
- przygotowuje pliki konfiguracyjne aplikacji.

## Instalacja nieinteraktywna
Jako `root`:
```bash
export FLASK_DOWNLOADER_ADMIN_PASSWORD='TwojeHasloAdmina'
apt-get update && apt-get install -y curl ca-certificates && curl -fsSL https://raw.githubusercontent.com/Q-Tronic/flask_downloader/main/scripts/install.sh | bash -s -- --non-interactive
```

## Po instalacji
Po zakończeniu instalator pokaże:
- adres panelu,
- katalog aplikacji,
- status usługi.

Domyślnie panel będzie dostępny pod adresem w stylu:
```text
http://IP_SERWERA:9999/
```

## Co znajdziesz w panelu
### Strona główna
- wklejanie jednego lub wielu linków,
- szybkie dodawanie `Wideo BEST` i `Audio BEST`,
- podgląd źródeł przed pobraniem.

### Pobrane pliki
- lista własnych plików zapisanych na serwerze,
- otwieranie playlist i plików,
- szybkie dodawanie audio do własnego radia.

### Zadania pobierania
- aktywne, oczekujące i zakończone pobrania,
- kolejka pobrań per użytkownik,
- podgląd postępu bez ręcznego odświeżania strony.

### Moje radio
- własna stacja per użytkownik,
- `AutoDJ`,
- biblioteka audio,
- `eRDS` i metadane,
- dane do nadawania live,
- start, stop, restart i pomijanie do następnego utworu.

### DLNA
- tylko dla administratora,
- zarządzanie klientami, kolekcjami i eksportem mediów,
- backend oparty o `Gerbera`.

### Konfiguracja
- tylko dla administratora,
- wybór aktywnego miejsca zapisu `lokalnie / udział sieciowy SMB-CIFS`,
- test połączenia udziału sieciowego z kontrolą odczytu i zapisu,
- montowanie i odmontowywanie udziału sieciowego z panelu WWW,
- utrzymanie `yt-dlp`, `ffmpeg`, `DLNA` i backendu radia,
- zarządzanie użytkownikami.

## Ponowne uruchomienie instalatora
Instalator można uruchomić ponownie. Nie powinien nadpisywać istniejących danych użytkowników ani bieżącej konfiguracji aplikacji.
