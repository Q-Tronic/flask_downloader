# AGENTS.md

## Cel projektu
- To jest panel Flask do ekstrakcji źródeł przez `yt-dlp`, pobierania plików na serwer i zarządzania lokalnymi plikami.
- UI i komunikaty mają być po polsku.

## Struktura projektu
- Root projektu ma pozostać możliwie czysty: cienki `app.py` jako entrypoint, kod aplikacji w pakiecie `flask_downloader/`, szablony w `templates/`, a assety frontendowe w `static/`.
- Pliki danych aplikacji nie powinny już leżeć w root projektu; docelowe miejsce to katalog `data/`.
- Aplikacja ma umieć czytać lokalny plik `.env` z override konfiguracji środowiskowej, zwłaszcza dla portu, sekretu sesji, nazw usług i bazowych ścieżek storage.
- JSON-y stanu aplikacji mają być prowadzone jako:
  - `data/config.json`
  - `data/jobs.json`
  - `data/users.json`
- Repo ma zawierać tylko pliki przykładowe dla środowiska i danych, np. `.env.example`, `data/config.example.json`, `data/jobs.example.json`, `data/users.example.json`; prawdziwe dane i sekrety nie mogą trafiać do GitHub.
- Przy migracji ze starego układu nie wolno zgubić istniejącej konfiguracji, użytkowników ani zadań; trzeba zachować zgodność wsteczną i bezpieczne przeniesienie danych.
- Po migracji i późniejszym sprzątaniu legacy plików backend ma umieć odzyskać krytyczne sekcje konfiguracji DLNA także z najnowszego zarchiwizowanego `flask_downloader_config.json` w `backups/`, jeśli bieżące `data/config.json` straciło `media_rules`, a klienci i kolekcje nadal istnieją.
- Jeśli stary rootowy `flask_downloader_config.json` nadal zawiera pełną konfigurację DLNA, a nowe `data/config.json` ma pustą sekcję `dlna`, aplikacja ma odzyskać tę sekcję z legacy configu zamiast zostawiać pustą bibliotekę.
- HTML i CSS nie powinny wracać do wielkich stringów osadzonych w Pythonie; wspólny layout ma iść przez `templates/base.html`, a style przez pliki w `static/css/`.
- Frontendowy JS widoków nie powinien wracać do dużych inline skryptów; wspólny shell ma siedzieć w `static/js/`, a logika konkretnych stron w `static/js/pages/`.
- Główny arkusz stylów ma być rozdzielony przynajmniej na `static/css/base.css`, `static/css/layout.css` i `static/css/components.css`, zamiast jednego wielkiego bloku utrzymywanego na stałe.
- Rozbijanie backendu robimy modułami: autoryzacja i użytkownicy mają trafiać do `flask_downloader/routes/` oraz `flask_downloader/stores/`, zamiast dokładania kolejnych tras CRUD z powrotem do monolitu.
- Wspólny shell layoutu ma być cięty na partiale w `templates/partials/`, zamiast dalszego rozpychania `base.html`.

## Ustalone zasady UX
- Panel ma działać możliwie w pełni AJAXowo, nie tylko na stronie ustawień.
- Kliknięcie przycisku, submit formularza albo użycie pola wyboru nie może powodować głupiego przeładowania strony ani skoku na górę, jeśli dana akcja może zostać obsłużona w miejscu.
- Wewnętrzna nawigacja między głównymi widokami aplikacji ma używać AJAX, a nie pełnego refreshu.
- Akcje w ustawieniach mają używać `fetch` i aktualizować widok w miejscu.
- Sukcesy i błędy w ustawieniach pokazujemy jako toasty lub komunikaty w UI, bez pełnego refreshu.
- Stan kart w ustawieniach ma być odświeżany cyklicznie z backendu.
- Po AJAXowej podmianie widoku trzeba sprzątać stare timery i listenery, żeby nie dublować requestów i handlerów.
- Elementy ukrywane przez atrybut `hidden`, zwłaszcza formularze akcji w ustawieniach, muszą być naprawdę niewidoczne także przy własnych stylach `display`; nie wolno dopuścić, żeby CSS typu `display: grid` nadpisywał ukrycie.
- Skrypty osadzone w widokach, które są podmieniane AJAXowo, muszą działać w lokalnym scope, np. przez IIFE; nie mogą deklarować globalnych `const`/`let`, bo po wejściu drugi raz na ten sam widok wyłożą się na redeklaracji i zostawią placeholdery.
- Panel `Konto` w bocznej kolumnie ma być zwięzły: bez rozwlekłych opisów uprawnień i bez list kafelków z możliwościami roli; status sesji ma być wyśrodkowany i czytelny zarówno dla `admin`, jak i `user`.

## Ustawienia i panel utrzymania
- Karta `yt-dlp` ma pokazywać:
  - wersję na serwerze,
  - najnowszą wersję,
  - status,
  - żywy pasek postępu i etapy aktualizacji,
  - przycisk aktualizacji tylko wtedy, gdy aktualizacja jest naprawdę potrzebna.
- Karta `ffmpeg` ma pokazywać:
  - wersję na serwerze,
  - najnowszy build,
  - źródło binarki,
  - używany build,
  - ścieżkę używaną przez `yt-dlp`,
  - żywy pasek postępu i etapy instalacji/aktualizacji,
  - przycisk instalacji/aktualizacji tylko wtedy, gdy jest potrzebny.
- Karta restartu usługi Flask też ma działać AJAXowo i odświeżać status bez reloadu.
- Zapis konfiguracji ma działać AJAXowo i od razu aktualizować pola/metryki w widoku.
- W `Konfiguracji` ma być też karta `Serwer DLNA` z:
  - wersją pakietu `gerbera` na serwerze,
  - kandydatem wersji z aktywnych repo `apt` dla danego systemu,
  - stanem usługi DLNA,
  - autostartem,
  - żywym paskiem postępu instalacji/aktualizacji,
  - przyciskiem instalacji/aktualizacji tylko wtedy, gdy pakiet naprawdę tego wymaga,
  - przejściem do pełnej zakładki `DLNA`.

## ffmpeg
- `ffmpeg` jest wymagany do łączenia osobnych strumieni audio i wideo.
- Projekt ma preferować lokalnie zarządzany `ffmpeg` w katalogu projektu i podawać jego ścieżkę do `yt-dlp` przez `ffmpeg_location`.
- Źródłem zarządzanego `ffmpeg` jest repozytorium `yt-dlp/FFmpeg-Builds`.
- Jeżeli `ffmpeg` nie jest dostępny, komunikat błędu ma jasno mówić, że trzeba go zainstalować z poziomu konfiguracji.

## Pobieranie audio
- Audio pobierane na serwer ma być finalnie zapisywane jako `mp3`.
- Konwersja audio ma używać `ffmpeg` przez `yt-dlp` postprocessor `FFmpegExtractAudio`.
- Docelowy codec: `mp3`.
- Docelowa jakość: najwyższa sensowna VBR dla MP3, czyli `q=0`.
- Trzeba jasno komunikować, że źródłowe `m4a` z YouTube nadal jest stratne, więc MP3 nie będzie bezstratne.
- `Pobierz na serwer` dla audio oznacza pobranie i konwersję do `mp3`.
- `Pobierz do przeglądarki` dla audio ma zwracać surowy plik źródłowy, np. `m4a` albo `webm`, bez udawania `mp3`.

## Progres i statusy
- Dla długich operacji administracyjnych trzeba pokazywać:
  - aktualny etap,
  - procent,
  - czas startu / zakończenia,
  - komunikat końcowy.
- Pasek postępu ma aktualizować się na bieżąco bez ręcznego odświeżania strony.
- Po zakończeniu zadania karta ma sama przejść w stan końcowy.
- Kolejka pobrań ma ograniczać równoległe pobieranie per użytkownik; domyślnie jeden użytkownik może mieć naraz maksymalnie `3` aktywne pobrania, a reszta ma czekać w kolejce.

## Instalator i deploy
- Projekt ma zawierać skrypt instalacyjny dla Debiana 10+ w `scripts/install.sh`.
- Instalator ma:
  - pytać o port aplikacji z timeoutem `30s` i domyślnym `9999`,
  - walidować zakres portu i wykrywać konflikt zajętego portu, ale pozwalać na ponowne uruchomienie instalatora dla tej samej istniejącej instancji na tym samym porcie,
  - tworzyć użytkownika Linux dla usługi,
  - tworzyć `.env`,
  - pytać o hasło pierwszego użytkownika `admin`,
  - hashować to hasło przed zapisaniem do `data/users.json`,
  - honorować wartości podane przez argumenty CLI albo zmienne środowiskowe bez ponownego dopytywania o te same pola,
  - nie nadpisywać istniejących danych aplikacji przy ponownym uruchomieniu,
  - pokazywać czytelny, kolorowy postęp i końcowe podsumowanie,
  - trzymać szczegółowe logi instalacji w osobnym pliku zamiast zalewać terminal pełnym outputem `apt` i `pip`.
- Projekt ma zawierać skrypt deploy przez SSH, który robi backup kodu, nie narusza `data/` ani `.env` i restartuje usługę po wdrożeniu.

## DLNA
- Backend serwera DLNA ma bazować na `Gerbera`.
- Aktualizacja `Gerbera` ma preferować oficjalne repo Gerbera zamiast przestarzałego pakietu Debiana, bo dopiero nowsze wersje poprawnie obsługują grupy klientów i logiczny layout kolekcji.
- Zakładka `DLNA` ma być dostępna z głównej nawigacji dla administratora i działać AJAXowo bez pełnych reloadów.
- Zakładka `DLNA` ma być możliwie zwarta i używalna:
  - zamiast jednej długiej ściany formularzy ma być podzielona na wewnętrzne panele / zakładki robocze,
  - listy klientów, kolekcji i wpisów mediów mają być możliwie zwarte, najlepiej z rozwijaniem edycji dopiero na żądanie,
  - edycja zawartości bukietu ma działać na jednej liście w jednej kolumnie, bez dwóch list obok siebie,
  - główny edytor bukietu ma używać checkboxów i zbiorczego zapisu widocznych pozycji jednym kliknięciem,
  - nazwy plików i folderów w edytorze bukietu mają być minimalistyczne i czytelne, z oszczędnym metatekstem,
  - klienci DLNA mają widzieć logiczny układ `bukiet -> pliki`, bez technicznych ścieżek systemowych typu `PC Directory/root/.../export/...`,
  - wyniki wyszukiwania mediów i długie listy mają używać przewijanych kontenerów, a nie rozpychać całej strony w nieskończoność.
- Domyślnie żaden klient nie ma dostępu do DLNA; dostęp dostają dopiero wpisy IP z whitelisty.
- Adresy klientów DLNA mają być ograniczone do sieci `192.168.0.0/16`.
- Klient DLNA ma mieć:
  - adres IP,
  - opis urządzenia,
  - przełącznik aktywności,
  - możliwość przypisania wielu kolekcji,
  - możliwość przypisania wielu użytkowników.
- Jedno urządzenie DLNA może mieć przypisanych wielu użytkowników, a jeden użytkownik może być przypisany do wielu urządzeń.
- Jeśli klient DLNA ma przypisanego użytkownika, ma widzieć dodatkowy root tego użytkownika obok bukietów:
  - `<username>/Video/Wszystkie Pliki`
  - `<username>/Video/YYYY-MM-DD`
  - `<username>/Audio/Wszystkie Pliki`
  - `<username>/Audio/YYYY-MM-DD`
- Root użytkownika w DLNA ma pokazywać tylko pliki należące do tego użytkownika, pogrupowane na `Video` i `Audio`, a potem na `Wszystkie Pliki` i foldery dat.
- W rootach użytkownika DLNA nie wracamy do pomocniczego folderu `Pozostałe`; pliki bez segmentu daty mają trafiać tylko do `Wszystkie Pliki`.
- `Wszystkie Pliki` w rootach użytkownika powinno być prezentowane przed folderami dat.
- Kolekcje DLNA są globalne i współdzielone między klientami.
- Jedno medium może należeć do wielu kolekcji.
- Musi istnieć wbudowana kolekcja `Wszystkie aktywne media`, która daje klientowi dostęp do całej aktywnej biblioteki DLNA.
- Media dla DLNA wybieramy jako:
  - cały folder,
  - pojedynczy plik,
  - z filtrowaniem po nazwie.
- Serwer DLNA ma wystawiać tylko media aktywne dla DLNA.
- Aplikacja ma budować własny katalog eksportu DLNA z symlinkami tylko do aktywnych mediów, zamiast wystawiać surowo całe katalogi pobrań.
- W katalogu eksportu DLNA pliki przypisane do bukietu mają leżeć możliwie płasko bez dodatkowych poziomów `owner/storage/data`, tak żeby klient po wejściu w bukiet widział od razu pliki.
- Zmiana kolekcji, klientów, wpisów mediów albo ustawień serwera DLNA ma zapisywać się bez reloadu i od razu synchronizować eksport DLNA.
- Zmiana kolekcji, klientów, przypisanych użytkowników, wpisów mediów albo ustawień serwera DLNA ma kończyć się pełnym, spójnym rebuiltem eksportu i odświeżeniem bazy Gerbera, a nie tylko częściową podmianą katalogów na żywym indeksie.
- Usunięcie pliku z panelu lub zakończenie pobierania powinno odświeżać bibliotekę DLNA tak, żeby eksport nie rozjeżdżał się z faktycznymi plikami.
- Martwe wpisy DLNA, wskazujące na pliki albo foldery już nieobecne na serwerze, mają być automatycznie usuwane z konfiguracji i z widoku DLNA.
- Klient DLNA nie ma widzieć obcych bukietów ani obcych rootów użytkowników jako pustych folderów; jeśli IP nie ma dostępu do danego rootu, ten root ma być ukryty całkowicie.
- Dla starych wersji `Gerbera` bez nowego JS-owego layoutu backend ma wybierać kompatybilny fallback, a nie wystawiać pustą bibliotekę.
- Przed restartem lub startem usługi DLNA backend ma walidować wygenerowany `config.xml`, jeśli zainstalowana wersja `gerbera` wspiera taką walidację.
- Konfiguracja `Gerbera` ma być składana zgodnie z możliwościami wersji pakietu z Debiana; nie wolno generować wpisów wymagających nowszych wersji, jeśli lokalny pakiet ich nie obsługuje.
- Dla starej `Gerbera 1.1.x` trzeba używać zgodnego `import-script` i płaskiego eksportu, żeby nie wracać do głębokiego `PC Directory` ani pustego root przez niekompatybilne nowsze hooki skryptowe; realne minimum tej wersji po stronie klienta to `Video -> All Video -> pliki`, bo pakiet nadal narzuca własny fallback layout.
- Dla nowszej `Gerbera 2.x/3.x` preferujemy własny JS-owy layout z rootem `bukiet -> pliki` i ukrytym `PC Directory`, a fizyczny eksport pod `/dlna` ma służyć jako backend dla skanowania i filtrów klientów, nie jako drugi widok dla użytkownika końcowego.
- Wspólna instancja `Gerbera 3.x` nadal ma praktyczne ograniczenie: ukrywanie top-level rootów per klient przez `group/client hide location` bywa nieskuteczne zarówno dla kontenerów z JS virtual-layout, jak i dla dynamicznych kontenerów. Jeśli potrzebne jest twarde `urządzenie widzi tylko swoje rooty i nic więcej`, to trzeba planować większą zmianę architektury niż samo dalsze strojenie obecnego shared-instance Gerbera.
- Skrócony root `/dlna` ma być prawdziwym katalogiem eksportu, a nie symlinkiem do starego runtime, bo Gerbera potrafi wtedy rozwinąć realpath i wrócić do rozwleczonego `root/flask_downloader/tools/...`.
- Stary katalog `tools/dlna/runtime/export` nie może być utrzymywany równolegle po migracji na `/dlna`, bo tworzy boczną ścieżkę przez `PC Directory` i rozwala izolację kolekcji między klientami.
- Usługa DLNA nie może wpadać w nieskończoną pętlę restartów przy złym configu; jeśli start się nie utrzymuje, panel ma pokazać diagnostykę i ostatni log zamiast udawać, że wszystko jest OK.
- Diagnostyka DLNA ma preferować realny log procesu `Gerbera`, a nie tylko ogólne komunikaty `systemd`, żeby było od razu widać błąd składni configu albo runtime.
- Restart i ponowny start DLNA muszą być odporne na stary błąd `Gerbera 1.1.x`, w którym zatrzymanie procesu kończy się `exit 1`; panel ma oceniać końcowy stan usługi po sekwencji `stop/reset-failed/start`, a nie traktować samego błędu zamykania jako automatyczną porażkę całej operacji.
- Sekwencja `stop/reset-failed/start` dla DLNA ma też być odporna na wolne zamykanie Gerbery pod `systemd`: timeout zatrzymania nie może zostawiać panelu w trwałym stanie `failed`, jeśli proces został już domknięty albo dobity przez `systemd`.
- Dla starych wersji `Gerbera`, które nie obsługują `--check-config`, backend nie może blokować zapisu/synchronizacji przez testowy runtime-probe; wystarczy lokalna walidacja poprawności XML, a faktyczny stan należy oceniać na prawdziwym starcie usługi.
- Serwer DLNA ma logować do pliku `gerbera.log` w runtime projektu, a administrator musi mieć prosty podgląd tego logu w przeglądarce pod adresem `/logs-dlna`; normalny start/restart usługi nie powinien czyścić tego logu.
- Log `gerbera.log` nie może rozrastać się bez końca: ma być ograniczony do około `5 MB`, a dla nowszej Gerbery trzeba preferować rotowanie logu zamiast pełnego debug streamu.
- Własna usługa DLNA aplikacji nie może startować Gerbery z flagą pełnego debugowania `-D` w normalnym trybie pracy, bo zalewa log i zamula panel administracyjny.
- Jeśli port DLNA jest zajęty przez systemową `gerbera.service` z pakietu Debiana, panel ma traktować to jako konflikt z własnym serwerem DLNA aplikacji i przed startem automatycznie zatrzymać oraz wyłączyć tę kolidującą usługę.

## Zachowanie pobierania i przejść
- `Pobierz na serwer` ma tylko dodać zadanie do kolejki i pokazać status/toast bez przymusowego przechodzenia na stronę zadań.
- Pole URL na stronie głównej ma przyjmować także wiele linków naraz; parser ma wyciągać wszystkie poprawne adresy `http/https` z całego pola, deduplikować je i zachowywać kolejność.
- Podstawowy przycisk `Pobierz dane` na stronie głównej ma nadal służyć tylko do pojedynczego linku; jeśli w polu są wielokrotne adresy, UI ma pokazać czytelny błąd zamiast próbować renderować jeden losowy wynik.
- Na stronie głównej obok `Pobierz dane` mają istnieć szybkie przyciski `Wideo BEST` i `Audio BEST`, które bez wchodzenia w szczegóły dodają do kolejki najlepsze dostępne źródło dla wszystkich linków z pola.
- Szybkie przyciski `BEST` po udanym dodaniu do kolejki mają pokazywać toast po prawej stronie i czyścić pole URL; przy częściowym błędzie pole powinno zostawiać tylko te linki, których nie udało się dodać.
- Pod formularzem URL na stronie głównej ma być zwięzły wybór `Dodaj po pobraniu do bukietu DLNA`; wybrany bukiet ma działać zarówno dla szybkich przycisków `BEST`, jak i dla zwykłego `Pobierz na serwer` z karty szczegółów źródła.
- Lista bukietów w tym szybkim wyborze ma być filtrowana do tych, do których bieżący użytkownik ma dostęp; `admin` widzi wszystkie zwykłe bukiety, a zwykły użytkownik tylko te wynikające z jego aktualnych przypisań DLNA.
- Jeśli job pobierania ma zapisany docelowy bukiet DLNA, po poprawnym zakończeniu pobierania backend ma automatycznie dopiąć pobrany plik do tego bukietu i zsynchronizować bibliotekę DLNA.
- Jeśli extractor zwraca nazwę serii / programu, nazwa pobieranego pliku ma ją prefiksować przed tytułem odcinka w czytelnym formacie `Seria - Tytuł`, zamiast zapisywać sam goły tytuł odcinka.
- Linki otwierające prawdziwe pliki, playlisty lub zewnętrzne strony mogą działać normalnie albo w nowej karcie, ale linki nawigujące po samym panelu mają zostać AJAXowe.
- Zmiana `Format` i `Rozmiar / jakość` na stronie głównej ma odświeżać szczegóły źródła bez skoku viewportu do góry; podczas ładowania nie wolno zwijać sekcji tak, żeby przeglądarka sama korygowała scroll.
- Ostrzeżenia i podpowiedzi dotyczące wybranego źródła, takie jak duplikaty na serwerze, inne jakości albo osobne audio, mają być pokazywane jako dymek w prawym górnym rogu zamiast rozpychać środek karty.
- Domyślny wybór źródła dla każdego serwisu ma preferować `wideo`, a dopiero potem najwyższą dostępną jakość; `audio` ma być tylko fallbackiem, gdy nie ma sensownego źródła wideo.
- Przy remisie jakości warto preferować bardziej praktyczny kontener, zwłaszcza `mp4`, ale nie kosztem głównej zasady `wideo + najwyższa jakość`.
- Górny status przestrzeni danych na stronie głównej ma być kompaktowym badge przy tytule `VLC Stream Extractor`, z prostą ikoną i stanem `online / offline`, a nie dużym zielonym lub czerwonym boksem pod nagłówkiem.
- Strona główna po zalogowaniu ma być zwięzła; nie wracamy do dodatkowych leadów typu `Wklej link...` ani do notek o pobieraniu do własnej przestrzeni pod formularzem.

## Użytkownicy i role
- Aplikacja ma mieć dwa poziomy ról: `admin` i `user`.
- Konto startowe ma być `admin / admin`, ale hasło nie może być trzymane jawnie; użytkownicy i hashe haseł mają być zapisywani w osobnym store.
- Gość, czyli niezalogowany użytkownik, ma widzieć tylko opis aplikacji i formularz logowania.
- Gość nie może widzieć:
  - listy plików,
  - listy pobrań,
  - formularza pobierania źródeł,
  - konfiguracji,
  - DLNA,
  - bezpośrednich URL-i do lokalnych plików.
- Zwykły użytkownik ma widzieć i obsługiwać tylko:
  - własne zadania pobierania,
  - własne pliki,
  - własne pobieranie nowych materiałów.
- Administrator ma widzieć wszystko oraz:
  - tworzyć użytkowników,
  - edytować login i rolę istniejących użytkowników z panelu `Konfiguracja`,
  - usuwać użytkowników,
  - ręcznie resetować hasła,
  - zmieniać własne hasło z sekcji `Konto` bez pełnego przeładowania całego panelu,
  - filtrować listę plików i listę zadań po użytkowniku,
  - usuwać cudze pliki i cudze zadania.
- Każdy zalogowany użytkownik ma mieć możliwość zmiany własnego hasła z sekcji `Konto` w bocznym panelu.
- Struktura katalogów użytkowników ma być:
  - `BASE/<user>/video/YYYY-MM-DD/...`
  - `BASE/<user>/audio/YYYY-MM-DD/...`
- Katalog bazowy użytkowników jest wspólny, ale każdy user ma własne poddrzewa `video` i `audio`.
- Stare pliki i stare rekordy zadań bez właściciela mają być migrowane do `admin`.
- Zmiana bazowego katalogu użytkowników w konfiguracji ma realnie przenosić istniejące dane i aktualizować ścieżki zapisane w zadaniach.
- Zwykły użytkownik nie może widzieć pełnych ścieżek systemowych typu `/mnt/...`; w UI pokazujemy tylko ścieżki względne i komunikaty ogólne.
- Usunięcie użytkownika ma usuwać:
  - konto,
  - jego katalogi,
  - jego pliki,
  - jego zadania,
  - jego powiązane wpisy DLNA.
- DLNA pozostaje funkcją tylko dla administratora.
- Dla dużych zmian systemu uprawnień trzeba utrzymywać bieżącą checklistę wdrożenia w repo, żeby dało się wznowić pracę po przerwaniu sesji bez ponownego audytu całego kodu.

## Zasady utrzymania tego pliku
- Przy każdej zmianie zachowania UI lub ważnej logiki administracyjnej trzeba zaktualizować ten plik.
- Nie wolno w kolejnych zmianach przypadkiem cofać zasad zapisanych tutaj.
