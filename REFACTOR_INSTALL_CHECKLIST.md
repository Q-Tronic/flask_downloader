# Checklist: Refaktoryzacja, Instalator, Deploy i GitHub

## Cel końcowy
- Rozbić obecny monolit na czytelną strukturę modułów.
- Trzymać kod, dane, frontend i runtime w osobnych miejscach.
- Zachować pełną zgodność funkcjonalną obecnej aplikacji.
- Nie zgubić istniejących danych użytkowników, zadań, konfiguracji ani DLNA.
- Doprowadzić projekt do stanu:
  - gotowy do wdrożenia na czysty Debian,
  - gotowy do aktualizacji przez SSH,
  - gotowy do bezpiecznego wrzucenia na GitHub.

## Zasady twarde
- Nie nadpisujemy ani nie kasujemy bez potrzeby:
  - `data/config.json`
  - `data/jobs.json`
  - `data/users.json`
- Każdy etap musi kończyć się lokalnym smoke testem.
- Każdy bezpieczny etap może być wdrożony na serwer bez utraty danych.
- UI i komunikaty pozostają po polsku.
- Nie wracamy do gigantycznych stringów HTML/CSS/JS w Pythonie.
- Każda większa zmiana struktury lub ważnej logiki aktualizuje `AGENTS.md`.
- Każdy etap ma własną bramkę jakości przed przejściem dalej.

## Stan obecny
- [x] Root ma cienki `app.py`.
- [x] Jest pakiet `flask_downloader/`.
- [x] Dane działają z `data/`.
- [x] Jest `templates/base.html`.
- [x] Jest `static/css/` i `static/js/`.
- [x] `auth/users` są już częściowo wydzielone.
- [x] Fundament został wdrożony na serwer i aplikacja wstała poprawnie.

---

## Etap 0: Checkpoint i bezpieczeństwo prac
- [x] Potwierdzić działającą kopię lokalną przed większą refaktoryzacją.
- [x] Potwierdzić dostęp SSH do serwera.
- [x] Potwierdzić, że serwer ma kopię danych w `data/`.
- [x] Wykonać backup kodu na serwerze przed pierwszym większym wdrożeniem.
- [x] Utrzymywać na bieżąco checklistę postępu w repo.
- [x] Przy każdym większym wdrożeniu zostawiać punkt powrotu na serwerze.

## Etap 1: Docelowa struktura projektu
- [x] Dodać pakiet `flask_downloader/`.
- [x] Zostawić cienki `app.py` jako entrypoint.
- [x] Utworzyć katalogi:
  - `flask_downloader/routes/`
  - `flask_downloader/services/`
  - `flask_downloader/stores/`
  - `flask_downloader/utils/`
  - `templates/`
  - `templates/pages/`
  - `templates/partials/`
  - `static/css/`
  - `static/js/`
  - `data/`
- [x] Dodać `flask_downloader/paths.py`.
- [x] Ustawić podstawowy `create_app()` w pakiecie.
- [ ] Docelowo przenieść bootstrap aplikacji z `legacy_app.py` do `__init__.py`.
- [ ] Ograniczyć `legacy_app.py` do roli przejściowej albo całkiem go usunąć.

### Bramka jakości
- [x] `python -m py_compile` przechodzi.
- [x] `import app` działa.
- [x] `/` zwraca `200`.

## Etap 2: Migracja i porządek danych
- [x] Przenieść obsługę danych do `data/`.
- [x] Dodać bezpieczną migrację ze starych plików root:
  - `flask_downloader_config.json`
  - `flask_downloader_jobs.json`
  - `flask_downloader_users.json`
- [x] Zachować zgodność wsteczną przy pierwszym uruchomieniu.
- [x] Nie usuwać automatycznie starych plików root na pierwszym etapie.
- [ ] Dodać narzędzie albo etap końcowy do uporządkowania starych plików po potwierdzeniu migracji.
- [ ] Ustalić finalny sposób wersjonowania schematu danych.
- [x] Rozdzielić wyraźnie:
  - config store
  - jobs store
  - users store

### Bramka jakości
- [x] Dane istnieją po migracji w `data/`.
- [x] Aplikacja po wdrożeniu nadal czyta dane poprawnie.
- [x] Żaden etap późniejszej refaktoryzacji nie wraca do ścieżek root JSON.

## Etap 3: Frontend i layout
- [x] Wyciągnąć `base.html`.
- [x] Wyciągnąć główne strony do `templates/pages/`.
- [x] Wyciągnąć CSS do `static/css/`.
- [x] Wyciągnąć wspólny JS do `static/js/`.
- [x] Przestawić renderowanie na `render_template(...)`.
- [ ] Rozbić duże widoki na partiale:
  - `settings`
  - `dlna`
  - `index`
  - `jobs`
  - `downloads`
- [x] Uporządkować nazwy partiali:
  - `_sidebar.html`
  - `_account_panel.html`
  - `_toast.html`
  - `_page_header.html`
- [ ] Rozdzielić CSS na pliki:
  - `base.css`
  - `layout.css`
  - `components.css`
  - opcjonalnie `pages/*.css`
- [ ] Rozdzielić JS na:
  - shell wspólny
  - inicjalizacja strony głównej
  - settings
  - dlna
  - jobs
  - downloads
- [ ] Dopiłować, by wszystkie skrypty AJAXowych widoków działały lokalnie w scope.

### Bramka jakości
- [x] Główny layout działa po wdrożeniu.
- [x] Nie ma regresji w AJAX navigation.
- [ ] Nie ma dublowania listenerów po przejściach.

## Etap 4: Auth i użytkownicy
- [x] Wydzielić store użytkowników do `flask_downloader/stores/users_store.py`.
- [x] Wydzielić trasy logowania i zmiany własnego hasła do `flask_downloader/routes/auth.py`.
- [x] Wydzielić trasy CRUD użytkowników do `flask_downloader/routes/users.py`.
- [x] Zostawić działanie bez zmian po wdrożeniu na serwer.
- [x] Wydzielić helpery sesji i auth do:
  - `flask_downloader/utils/auth.py`
  - albo `flask_downloader/services/auth_service.py`
- [x] Wynieść:
  - `is_authenticated`
  - `is_admin_authenticated`
  - `get_current_username`
  - `get_current_user_role`
  - `safe_next_url`
  - `set_ui_flash`
  - `pop_ui_flash`
- [x] Ograniczyć zależności auth/users od `legacy_app.py`.
- [ ] Dodać przejrzyste warstwy:
  - store
  - auth helpers
  - routes
- [x] Upewnić się, że tworzenie usera nadal tworzy mu katalogi `video/audio`.
- [x] Upewnić się, że reset hasła, zmiana loginu i usunięcie usera nadal działają.

### Bramka jakości
- [x] Logowanie i wylogowanie działają.
- [x] Zmiana własnego hasła działa.
- [x] CRUD userów nie wywalił aplikacji po wdrożeniu.
- [x] Admin/user permissions nadal są poprawne end-to-end.

## Etap 5: Downloads i jobs
- [x] Wydzielić trasy pobierania do `flask_downloader/routes/downloads.py`.
- [x] Wydzielić trasy zadań do `flask_downloader/routes/jobs.py`.
- [ ] Wydzielić logikę pobrań do `flask_downloader/services/download_service.py`.
- [ ] Wydzielić logikę źródeł do `flask_downloader/services/source_service.py`.
- [ ] Wydzielić logikę kolejki i jobów do `flask_downloader/services/jobs_service.py`.
- [x] Wydzielić zapis jobów do `flask_downloader/stores/jobs_store.py`.
- [ ] Wynieść helpery statusów, filtrów i ownerów.
- [ ] Zachować:
  - owner_username
  - filtrowanie po userze
  - uprawnienia admin/user
  - usuwanie zadań
  - anulowanie zadań
- [ ] Utrzymać zachowanie:
  - `Pobierz na serwer` tylko dodaje zadanie
  - brak wymuszonego przejścia na stronę jobs
- [ ] Sprawdzić audio/video flow po wydzieleniu.

### Bramka jakości
- [x] Dodawanie zadania działa.
- [x] Lista jobs działa.
- [x] Filtrowanie jobs po userze działa.
- [x] Pobrania zwykłego usera nie przeciekają adminowi poza celowym filtrem i odwrotnie.

## Etap 6: Settings i maintenance
- [x] Wydzielić trasy ustawień do `flask_downloader/routes/settings.py`.
- [x] Wydzielić logikę konfiguracji do `flask_downloader/stores/config_store.py`.
- [ ] Wydzielić ffmpeg do `flask_downloader/services/ffmpeg_service.py`.
- [ ] Wydzielić yt-dlp do `flask_downloader/services/ytdlp_service.py`.
- [x] Wydzielić maintenance taski i progres do `flask_downloader/services/maintenance_service.py`.
- [x] Wydzielić restart usługi Flask do osobnego helpera/system service.
- [ ] Utrzymać polling stanu kart ustawień.
- [ ] Zachować AJAX:
  - zapis konfiguracji
  - check/update yt-dlp
  - check/install ffmpeg
  - restart usługi
- [ ] Sprawdzić, że statusy, paski postępu i etapy nadal się odświeżają bez reloadu.

### Bramka jakości
- [x] Settings page działa bez reloadów.
- [x] ffmpeg karta działa.
- [x] yt-dlp karta działa.
- [ ] restart usługi działa.

## Etap 7: DLNA
- [x] Wydzielić trasy DLNA do `flask_downloader/routes/dlna.py`.
- [ ] Wydzielić logikę kolekcji, klientów i biblioteki do `flask_downloader/services/dlna_service.py`.
- [ ] Wydzielić konfigurację Gerbery do osobnego modułu/serwisu.
- [ ] Wydzielić sync eksportu DLNA do osobnego serwisu.
- [ ] Wydzielić logikę whitelist i dostępu klientów.
- [ ] Wydzielić logikę restartu/startu/stopu usługi DLNA.
- [ ] Wydzielić logikę walidacji `config.xml`.
- [ ] Zachować:
  - globalne kolekcje
  - wielu klientów na wiele kolekcji
  - `Wszystkie aktywne media`
  - whitelist `192.168.0.0/16`
  - auto-prune martwych wpisów
  - szybki sync po zmianach i po pobraniach/usunięciach
- [ ] Zachować kompatybilność:
  - fallback dla starej Gerbery
  - nowy layout dla nowszej Gerbery
- [ ] Zachować diagnostykę:
  - log DLNA
  - status usługi
  - restart odporny na stare błędy `Gerbera 1.1.x`

### Bramka jakości
- [x] Zakładka DLNA działa po AJAX bez reloadów.
- [ ] Kolekcje, klienci i edytor bukietów działają.
- [ ] Reguły dostępu klientów działają.
- [ ] TV/laptop widzą właściwe media po sync.
- [x] Log DLNA i diagnostyka nadal działają.

## Etap 8: Wspólne helpery i sprzątanie monolitu
- [ ] Wydzielić helpery ścieżek do `flask_downloader/utils/paths.py` albo zostawić obecne i ujednolicić.
- [ ] Wydzielić helpery formatowania do `flask_downloader/utils/formatting.py`.
- [ ] Wydzielić helpery odpowiedzi/JSON do `flask_downloader/utils/responses.py`.
- [x] Wydzielić helpery sieciowe/systemowe do `flask_downloader/utils/network.py` lub `services/system_service.py`.
- [ ] Posprzątać importy po wydzieleniach.
- [ ] Ograniczyć zmienne globalne w `legacy_app.py`.
- [ ] Przenieść rejestrację tras do jednego miejsca bootstrapu.
- [ ] Zmniejszyć `legacy_app.py` do przejściowego minimum.
- [ ] Docelowo:
  - albo usunąć `legacy_app.py`,
  - albo przemianować już czysty moduł na normalny bootstrap.

### Bramka jakości
- [ ] Żaden nowy moduł nie wymaga kopiowania połowy starego pliku.
- [ ] `legacy_app.py` jest wyraźnie mniejszy niż dziś.

## Etap 9: Testy lokalne
- [x] Smoke test login/logout.
- [x] Smoke test zmiany własnego hasła.
- [x] Smoke test CRUD userów.
- [ ] Smoke test pobierania źródła.
- [ ] Smoke test dodania joba.
- [x] Smoke test listy jobs.
- [x] Smoke test listy plików.
- [x] Smoke test settings.
- [ ] Smoke test ffmpeg/yt-dlp cards.
- [x] Smoke test DLNA settings page.
- [x] Smoke test AJAX navigation.
- [ ] Smoke test przeładowań partiali i cleanup timerów.

## Etap 10: Wdrożenia etapowe na serwer
- [x] Wdrożyć fundament.
- [x] Wdrożyć pierwszy moduł auth/users.
- [x] Wdrożyć etap downloads/jobs.
- [x] Wdrożyć etap settings/maintenance.
- [x] Wdrożyć etap DLNA.
- [x] Po każdym wdrożeniu:
  - backup kodu,
  - upload tylko potrzebnych plików,
  - restart usługi,
  - kontrola `systemctl status`,
  - szybki test HTTP,
  - potwierdzenie, że `data/*.json` są nienaruszone.

## Etap 11: Przygotowanie pod GitHub
- [x] Dodać `.gitignore`.
- [x] Dodać `.env.example`.
- [x] Dodać `data/config.example.json`.
- [x] Dodać ewentualny `data/users.example.json` tylko jeśli będzie sensowny i bezpieczny.
- [x] Dodać `README.md`.
- [x] Opisać instalację, update i deploy.
- [ ] Upewnić się, że do repo nie trafią:
  - prawdziwe JSON-y z danymi
  - `.env`
  - logi
  - backupy
  - runtime DLNA
  - sekrety i hasła
  - prywatne hosty i ścieżki
- [x] Sprawdzić ręcznie, czy w kodzie nie zostały twardo wpisane wrażliwe dane.

### Bramka jakości
- [ ] Repo jest czyste i gotowe do publikacji.
- [ ] Projekt da się uruchomić z plikami `.example`.

## Etap 12: Instalator
- [x] Dodać katalog `scripts/`.
- [x] Przygotować `scripts/install.sh`.
- [ ] Opcjonalnie rozbić instalator na helpery:
  - `scripts/lib/ui.sh`
  - `scripts/lib/system.sh`
  - `scripts/lib/config.sh`
- [x] Wykrywać Debiana przez `/etc/os-release`.
- [x] Obsłużyć Debiana 10+.
- [x] Instalować zależności systemowe.
- [x] Tworzyć użytkownika Linux dla aplikacji.
- [x] Nadawać właściwe właścicielstwo i prawa katalogom.
- [x] Tworzyć katalogi:
  - kodu
  - `data/`
  - logów
  - runtime
  - DLNA
- [x] Tworzyć `.env` z potrzebnymi ustawieniami.
- [x] Pytać o port aplikacji:
  - timeout `30s`
  - domyślnie `9999`
- [x] walidacja zakresu i zajętości portu
- [x] Pytać o hasło pierwszego użytkownika `admin`.
- [x] Wymagać powtórzenia hasła admina.
- [x] Hashować hasło przed zapisaniem do `users.json`.
- [x] Nie nadpisywać istniejących danych, jeśli instalacja leci drugi raz.
- [x] Generować usługi `systemd`.
- [ ] Opcjonalnie pytać, czy włączyć DLNA.
- [ ] Opcjonalnie instalować Gerberę i ffmpeg.
- [x] Pokazywać kolorowy, czytelny interfejs terminalowy.
- [x] Pokazywać procentowy postęp i opisy etapów.
- [x] Na końcu pokazać podsumowanie:
  - URL aplikacji
  - port
  - user systemowy
  - status usług
  - lokalizacja danych

### Bramka jakości
- [x] Instalator działa na czystym Debianie.
- [x] Po instalacji aplikacja wstaje.
- [x] Po instalacji admin może się zalogować ustawionym hasłem.

## Etap 13: Deploy i aktualizacje przez SSH
- [x] Przygotować `scripts/deploy.sh`.
- [x] Upewnić się, że deploy podmienia tylko kod i assety.
- [x] Nie ruszać przez deploy:
  - `data/`
  - `.env`
  - logów
- [x] Dodać backup przed deployem.
- [x] Dodać restart usług po deployu.
- [x] Dodać podstawową walidację po deployu:
  - status usługi
  - odpowiedź HTTP
  - opcjonalnie szybki health check

### Bramka jakości
- [x] Aktualizacja kodu działa jednym poleceniem.
- [x] Dane pozostają nienaruszone.

## Etap 14: Git i GitHub
- [x] Ustawić lokalne repo do finalnego commitu.
- [x] Zweryfikować jeszcze raz `.gitignore`.
- [x] Sprawdzić `git status`, czy nie łapiemy danych i sekretów.
- [x] Przygotować pierwszy czysty commit po refaktoryzacji.
- [x] Przygotować branch `main`.
- [ ] Przygotować remote do GitHub.
- [ ] Wypchnąć projekt na GitHub, jeśli autoryzacja będzie działać.
- [ ] Jeśli push nie będzie możliwy z sesji, zostawić repo gotowe do jednego `git push`.

## Etap 15: Finalny odbiór całości
- [ ] Pełny przegląd działania lokalnie.
- [ ] Pełny przegląd działania na serwerze.
- [ ] Kontrola danych:
  - userzy
  - joby
  - config
  - DLNA
- [ ] Kontrola UI:
  - brak reloadów tam, gdzie ma być AJAX
  - brak rozsypanych stylów po wyciągnięciu do static
  - brak błędów JS po wielokrotnym wejściu w te same widoki
- [ ] Kontrola instalatora.
- [ ] Kontrola deployu.
- [ ] Kontrola gotowości GitHub.

---

## Kolejność wykonania bez dalszych zmian scope
1. Dokończyć `auth/users`.
2. Rozciąć `downloads/jobs`.
3. Rozciąć `settings/maintenance`.
4. Rozciąć `DLNA`.
5. Posprzątać helpery i odchudzić monolit.
6. Dociąć frontend na partiale i lepiej rozdzielone CSS/JS.
7. Zrobić pełne smoke testy lokalne.
8. Zrobić etapowe smoke testy na serwerze.
9. Przygotować repo pod GitHub.
10. Zrobić instalator.
11. Zrobić deploy script.
12. Zrobić finalny przegląd i publikację.

## Najbliższy kolejny krok po komendzie `ROBIMY`
- [ ] Dokończyć rozbicie serwisów biznesowych poza `legacy_app.py`, zwłaszcza `downloads/jobs`, `settings/maintenance` i `DLNA`.
