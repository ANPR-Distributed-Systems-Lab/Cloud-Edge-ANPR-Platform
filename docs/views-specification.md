# Specyfikacja widoków 1–6 — źródło prawdy

Treść przepisana dosłownie z diagramu architektury `Inżynierka (2).drawio` (stan na 12.10.2026).

**Zasady:**
- Ten plik jest źródłem prawdy o tym, **co** robi każdy widok i jakie dane zwraca. Kontrakt OpenAPI, model bazy i frontend muszą być z nim zgodne.
- Zmiana wymagań = najpierw zmiana diagramu (uzgodniona w zespole), potem tego pliku, potem kodu.
- Świadome odstępstwa implementacji od diagramu są wpisane w sekcji „Odstępstwa” na końcu — z uzasadnieniem.

| Widok | Backend | Baza | Frontend |
|---|---|---|---|
| 1 | MS2 Alerts-And-Views-Service | PostgreSQL | Angular |
| 2 | MS2 Alerts-And-Views-Service | PostgreSQL / PostGIS | Angular |
| 3 | MS2 Alerts-And-Views-Service | PostgreSQL / PostGIS | Angular |
| 4 | MS1 Device-Management-Service | DynamoDB | Angular |
| 5 | MS1 Device-Management-Service | DynamoDB | Angular |
| 6 | MS2 Alerts-And-Views-Service | PostgreSQL | Angular |

---

## Widok 1: Panel wyszukiwania i analizy ANPR

**Opis funkcjonalny:**
- Centralna wyszukiwarka tablic rejestracyjnych wyposażona w mechanizm podpowiedzi (Autocomplete).
- Możliwość precyzyjnego filtrowania danych po numerze rejestracyjnym oraz przedziale czasowym (od-do).
- Prezentacja wyników w dwóch alternatywnych formach: dynamicznej mapy z pinezkami lokalizacji oraz szczegółowej listy.
- Dedykowana zakładka „Galeria zdjęć” wyświetlająca zdjęcia pojazdów.

**Zwracany kontrakt danych (Response Payload):**
- id_konta, id_urządzenia, tablica_rejestracyjna, datetime, współrzędne (GPS), s3_key

**Wymagania indeksacji (PostgreSQL Optymalizacja):**
- (detections) Zapytanie optymalizowane w bazie przez indeksy: B-Tree (id_konta), B-Tree (tablica_rejestracyjna) oraz B-Tree (datetime).

---

## Widok 2: Analiza radialna i weryfikacja tras (PostGIS)

**Opis funkcjonalny:**
- Zaawansowane wyszukiwanie zdarzeń w oparciu o zadany punkt geograficzny i promień (np. w odległości X metrów od współrzędnych) oraz przedział czasowy.
- Wizualizacja na mapie miejsc wykrycia pojazdów (zdjęcia ANPR) nałożona na pełną, wyrenderowaną trasę przejazdu urządzenia brzegowego (Raspberry Pi).
- Funkcja pozwala na precyzyjne odtworzenie ścieżki poruszania się samochodu w celu potwierdzenia lub wykluczenia obecności w danym miejscu i czasie.

**Zwracany kontrakt danych (Response Payload):**
- Dane detekcji (ANPR): id_konta, id_urządzenia, tablica_rejestracyjna, datetime, współrzędne (GPS), s3_key
- Telemetria urządzenia (Ślad GPS): id_konta, współrzędne_urządzenia, datetime

**Wymagania indeksacji (PostgreSQL / PostGIS Optymalizacja):**
- Dla danych ANPR (detections): Wyszukiwanie optymalizowane przez indeksy B-Tree (id_konta), przestrzenny GiST (współrzędne) oraz B-Tree (datetime).
- Dla śladu GPS (device_locations): Wyszukiwanie optymalizowane przez indeksy B-Tree (id_konta), przestrzenny GiST (współrzędne) oraz B-Tree (datetime).

---

## Widok 3: Panel główny i monitoring w czasie rzeczywistym (Live Feed)

**Opis funkcjonalny:**
- Główny pulpit operacyjny systemu wyświetlający mapę z bieżącą pozycją pojazdu (Raspberry Pi).
- Po prawej stronie znajduje się dynamiczna lista zdarzeń (Live Feed) odświeżana w czasie rzeczywistym, prezentująca najnowsze detekcje ANPR.
- Mapa wizualizuje aktualną pozycję samochodu oraz wyrenderowaną trasę przejazdu zdefiniowaną czasowo (np. z ostatnich 20 minut), umożliwiając bieżący nadzór nad potokiem telemetrycznym.

**Zwracany kontrakt danych (Response Payload):**
- Dane detekcji (ANPR): id_konta, id_urządzenia, tablica_rejestracyjna, datetime, współrzędne (GPS), s3_key
- Telemetria urządzenia (Ślad GPS): id_konta, współrzędne_urządzenia, datetime

**Wymagania indeksacji (PostgreSQL / PostGIS Optymalizacja):**
- Dla danych ANPR (detections): Wyszukiwanie optymalizowane przez indeksy B-Tree (id_konta) oraz B-Tree (datetime).
- Dla śladu GPS (device_locations): Wyszukiwanie optymalizowane przez indeksy B-Tree (id_konta) oraz B-Tree (datetime).

---

## Widok 4: Podgląd i edycja ustawień Raspberry Pi

**Opis funkcjonalny:**
- Panel administracyjny dedykowany do zdalnego zarządzania i konfiguracji urządzeń brzegowych.
- Umożliwia podgląd oraz modyfikację parametrów operacyjnych skryptu na RPi, takich jak długość czasu blokady ponownego wysyłania zdjęć dla tej samej tablicy (cooldown), konfiguracja wielkości paczek danych przy wysyłaniu lokalnych kolejek ze skanami pojazdów oraz żądaniach o PreSigned URL, a także parametryzacja progów detekcji modelu uczenia maszynowego (ML).

**Zwracany kontrakt danych (Response Payload):**
- id_urządzenia, cooldown_na_rejestracje, parametry_batchowania, parametry_modelu_ML

**Wymagania indeksacji (DynamoDB Optymalizacja):**
- (device_configurations) Odczyt i zapis punktowy optymalizowany bezpośrednio przez klucz główny (Partition Key): PK - id_urządzenia (brak Sort Key).

---

## Widok 5: Panel stanu i diagnostyki sprzętowej urządzeń

**Opis funkcjonalny:**
- Ekran diagnostyczny prezentujący w czasie rzeczywistym aktualny stan techniczny oraz wydajność operacyjną urządzenia brzegowego. Wyświetla parametry statusu połączenia sieciowego (Heartbeat), stopień zapełnienia i stan lokalnych kolejek buforujących na Raspberry Pi, wydajność potoku przetwarzania wideo (analiza klatek i FPS), a także metryki sprzętowe systemu operacyjnego, w tym temperaturę procesora, procentowe użycie procesora (CPU usage) oraz stopień wykorzystania pamięci operacyjnej (RAM usage).

**Zwracany kontrakt danych (Response Payload):**
- id_urządzenia, datetime, status_połączenia, stan_lokalnych_kolejek, processing_fps, cpu_temperature, cpu_usage, ram_usage

**Wymagania indeksacji (DynamoDB Optymalizacja):**
- (device_statuses) Odczyt historii stanów oraz zapis telemetryczny realizowany przez klucz złożony: PK - id_urządzenia (Partition Key) oraz SK - datetime (Sort Key).

---

## Widok 6: Panel zarządzania alertami

**Opis funkcjonalny:**
- Centrum zarządzania alertami systemowymi, umożliwiające pełną obsługę (dodawanie, usuwanie i modyfikowanie) wpisów na czarnej liście poszukiwanych pojazdów.
- Ekran prezentuje kompletną listę zdefiniowanych reguł z możliwością sortowania według daty utworzenia alertu oraz czasu jego ostatniego wyzwolenia w terenie.
- Interfejs pozwala na interaktywne kliknięcie w wybrany alert, co natychmiastowo wywołuje i wyświetla pełną historię wszystkich dotychczasowych detekcji powiązanych z danym samochodem.

**Zwracany kontrakt danych (Response Payload):**
- Dane konfiguracji alertu: id_konta, tablica_rejestracyjna, czas_utworzenia, tekst_alertu, czas_ostatniego_wykrycia
- Powiązane rekordy detekcji (ANPR): id_konta, id_urządzenia, tablica_rejestracyjna, datetime, współrzędne (GPS), s3_key, id_alertu

**Wymagania indeksacji (PostgreSQL / PostGIS Optymalizacja):**
- Dla danych konfiguracji (alerts): Wyszukiwanie i sortowanie optymalizowane przez indeksy B-Tree (id_konta), B-Tree (tablica_rejestracyjna), B-Tree (czas_utworzenia) oraz B-Tree (czas_ostatniego_wykrycia).
- Dla powiązanych detekcji (detections): Wyszukiwanie historii powiązanej z konkretnym alertem optymalizowane przez indeks B-Tree (id_alertu).

---

## Odstępstwa

Proponowane odstępstwa implementacji od diagramu. Status: `propozycja` (czeka na zgodę zespołu) / `uzgodnione`.
W kontrakcie OpenAPI odwołania mają postać `D1`–`D18` (bez znaku `#`, który w YAML zaczyna komentarz).

| Nr | Diagram | Implementacja | Uzasadnienie | Status |
|---|---|---|---|---|
| D1 | Osobne B-Tree na `id_konta` i `datetime` | Indeksy złożone, np. `(id_konta, datetime DESC)`, `(id_konta, tablica_rejestracyjna, datetime DESC)` | Każde zapytanie filtruje jednocześnie po koncie i czasie — jeden indeks złożony obsługuje oba warunki | propozycja |
| D2 | Współrzędne jako `GEOMETRY` | `GEOGRAPHY(Point, 4326)` | `ST_DWithin` na geography liczy promień w metrach (Widok 2), na geometry 4326 — w stopniach | propozycja |
| D3 | `id_konta` w każdej odpowiedzi | Brak `id_konta` w odpowiedziach API | Konto wynika z tokenu; pole nic nie wnosi dla frontendu. Nigdy nie jest parametrem wejściowym | propozycja |
| D4 | `s3_key` w odpowiedzi | `imageUrl` (presigned GET, krótki czas ważności) | Bucket jest prywatny — przeglądarka nie wyświetli zdjęcia z samego klucza (Galeria, Widok 1) | propozycja |
| D5 | Autocomplete w `GET /views/anpr-search` | Osobny `GET /detections/plate-suggestions` | Inna, lżejsza odpowiedź odpytywana przy każdym znaku | propozycja |
| D6 | Brak `GET /alerts/{id}` | Dodany endpoint | Formularz edycji i odświeżenie po 409 | propozycja |
| D7 | `alerts` bez id i wersji | `id_alertu` (UUID), `version` | Endpointy używają `{id_alertu}`; `version` chroni przed nadpisaniem równoczesnej edycji (409) | propozycja |
| D8 | `detections` bez id detekcji | `detection_id` (UUID nadawane przez RPi) | Idempotentny konsumer SQS — duplikat wiadomości nie tworzy drugiego rekordu | propozycja |
| D9 | Pola odpowiedzi wg „Zwracany kontrakt danych” | Dodatkowe pola i reguły: `alertId` w detekcjach wszystkich widoków; `deviceId` w trasach; `center`, `radiusMeters`, `truncated` (Widok 2, osobno dla detekcji i dla trasy); `ocrConfidence`, `detectorConfidence` z ingestu; `nextCursor`, `hasMore`, `lastSeenAt`, `lastPosition` (Widok 3); `lastDetectedAt` w podpowiedziach; jeden alert na tablicę w koncie (409 `ALERT_ALREADY_EXISTS`) | Pola tylko dodane (zgodne wstecz) — ułatwiają frontendowi rysowanie mapy i odpytywanie przyrostowe; unikalność alertu zapobiega duplikatom na czarnej liście | propozycja |
| D10 | Brak zasad stronicowania dla mapy i RPi | Bez stronicowania, ale z limitem: Widok 2 — max 5000 detekcji (najnowsze) + flaga `truncated`, trasa z co najwyżej jednym punktem na `trackIntervalSeconds` (parametr żądania, max 180 s) i max 5000 punktów (najnowsze) + flaga `truncated`, przedział czasu max 7 dni, promień max 5 km; lista alertów dla RPi — pełna lista | Mapa i urządzenie potrzebują kompletu danych naraz; limit chroni bazę przed zapytaniem o miesiące danych. Wyjątek od reguły „size max 100” | uzgodnione |
| D11 | Ścieżki `/api/v1/views/...` | `/api/v1/detections/search`, `/plate-suggestions`, `/radial-analysis`, `/live-feed` | Adres opisuje zasób, a nie ekran frontendu | uzgodnione |
| D12 | Zakładka „Galeria zdjęć” w Widoku 1 | Usunięta z planów: wyniki to mapa i lista | Zmniejszenie zakresu | uzgodnione |
| D13 | Wyszukiwanie w Widoku 1 z dopasowaniem częściowym | Opcjonalne `plate` jako dopasowanie dokładne (fragmenty obsługuje `plate-suggestions`); `from` i `to` opcjonalne, pominięta strona zakresu nie ma ograniczenia; `size` max 1000 zamiast osobnego endpointu dla mapy | Prefiks nie pozwalał znaleźć dokładnie `WA1234` bez `WA12345`; mapa dostaje wyniki z tego samego endpointu | uzgodnione |
| D14 | `id_alertu` w `detections`, `GET /alerts/{id_alertu}/detections` | Bez kolumny i bez endpointu: historia alertu to `GET /detections/search?plate=...`, a `alertId` w odpowiedziach wynika z pary konto i tablica | Historia dotyczy samochodu, więc obejmuje też detekcje sprzed utworzenia alertu; usunięcie alertu niczego nie psuje | uzgodnione |
| D15 | `GET /devices/{id_urzadzenia}/alerts` | Usunięty: RPi korzysta z `GET /alerts` i dostaje pełną listę właściciela z `ETag`, człowiek dostaje strony bez `ETag` | Alerty są na poziomie konta, więc wszystkie urządzenia konta mają tę samą listę | uzgodnione |
| D16 | Modyfikacja alertu | `PUT` zmienia tylko `alertText`, tablica jest niezmienna (poprawka to usunięcie i nowy alert) | Alert jest tożsamy z tablicą, a edycja tablicy nie miała określonej semantyki | uzgodnione |
| D17 | `czas_ostatniego_wykrycia` przechowywany w `alerts` | `lastDetectedAt` liczony przy odczycie: najpóźniejsze `detectedAt` tej tablicy w koncie (indeks `(account_id, plate, detected_at DESC)`) | Zawsze zgodny z detekcjami, także dostarczonymi z opóźnieniem (store-and-forward); konsument nie modyfikuje alertów, więc nie podbija ich `version` | uzgodnione |
| D18 | Brak pobrania pojedynczej detekcji | Dodany `GET /detections/{detectionId}` | Szczegóły detekcji otwieranej z listy lub mapy | uzgodnione |

---

## Pytania otwarte (do uzgodnienia w zespole)

1. Kto zatwierdza odstępstwa D1–D10? Do czasu zgody kontrakt jest wersją roboczą (`0.x`).
2. Czas ważności presigned URL zdjęć (D4) — zbuforowane strony przestaną działać po wygaśnięciu.
3. Limit spoza diagramu: okno Live Feed max 60 min — akceptujemy?

---

## Znane ograniczenia

1. **Widok 3, kursor Live Feed.** Kursor idzie po kolejności zapisu detekcji (czas zapisu, potem `detectionId`), więc detekcje z jednej paczki o identycznym czasie zapisu nie giną. Dwie paczki zapisywane równocześnie mogą zakończyć transakcje w innej kolejności, niż je rozpoczęły, dlatego Live Feed zwraca tylko detekcje zapisane co najmniej 2 sekundy przed żądaniem. Działa to pod warunkiem, że transakcja konsumenta zapisującego paczkę trwa krócej niż 2 sekundy; dłuższa transakcja może zostać przeskoczona przez kursor. Koszt: nowe detekcje pojawiają się w Live Feed z opóźnieniem około 2 sekund. Deduplikacja po stronie klienta nie jest potrzebna.
