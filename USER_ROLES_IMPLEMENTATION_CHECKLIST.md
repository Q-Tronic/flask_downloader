# Checklist: Uzytkownicy I Role

## Uzgodniony zakres
- Role: `admin` i `user`.
- Konto startowe: `admin / admin`.
- Hasla trzymane jako hash.
- Gosc widzi tylko opis strony i logowanie.
- Zwykly user:
  - moze dodawac pobrania,
  - widzi tylko swoje zadania,
  - widzi tylko swoje pliki,
  - moze usuwac tylko swoje pliki,
  - nie widzi konfiguracji ani DLNA.
- Admin:
  - widzi wszystko,
  - tworzy i usuwa uzytkownikow,
  - resetuje hasla recznie,
  - moze podgladac widok plikow i zadan innych userow,
  - moze usuwac cudze media i zadania,
  - ma dostep do DLNA i konfiguracji.
- Struktura plikow:
  - `BASE/<user>/video/YYYY-MM-DD/...`
  - `BASE/<user>/audio/YYYY-MM-DD/...`
- Stare pliki i stare wpisy zadan migrujemy do `admin`.
- Usuniecie uzytkownika usuwa jego pliki, foldery, zadania i powiazania.

## Postep wdrozenia
- [x] Rozpisana checklista wdrozenia w repo.
- [x] Dodac store uzytkownikow, role, hashowanie hasel i sesje usera.
- [x] Dodac migracje startowa konta `admin / admin`.
- [x] Dodac nowy katalog bazowy userow i helpery sciezek `BASE/<user>/video|audio/...`.
- [x] Zmigrowac stare pliki i stare rekordy zadan do `admin`.
- [x] Dopisac wlasciciela do zadan i filtrowanie zadan per user.
- [x] Dopisac wlasciciela do plikow i filtrowanie plikow per user.
- [x] Zabezpieczyc pobieranie plikow URL-em tak, by user nie pobral cudzego pliku.
- [x] Ograniczyc usuwanie plikow do wlasciciela lub admina.
- [x] Ograniczyc usuwanie zadan do wlasciciela lub admina.
- [x] Zmienic widok goscia na opis + logowanie bez listy plikow i pobieran.
- [x] Zmienic boczny panel i sesje z trybu `admin only` na normalnych uzytkownikow.
- [x] Dodac panel admina do tworzenia, usuwania userow i resetu hasel.
- [x] Dodac adminowi filtr widoku plikow i zadan po uzytkowniku.
- [x] Ukryc pelne sciezki systemowe dla zwyklych userow.
- [x] Ograniczyc DLNA tylko do admina i dopasowac biblioteke DLNA do nowych sciezek.
- [x] Zaktualizowac `AGENTS.md`.
- [x] Sprawdzic migracje, uprawnienia, AJAX i podstawowe endpointy.

## Notatki robocze
- Obecnie projekt ma tylko sesje `admin_logged_in` i wspolne katalogi/rekordy.
- Obecne dane historyczne z `flask_downloader_jobs.json` nie maja wlasciciela.
- Trzeba uwazac na bezpieczne kasowanie katalogow tylko wewnatrz katalogu bazowego userow.
