# Jak przechowujemy dane

Inwentaryzacja danych Energy Advisora (ZP-130): co zbieramy, po co, gdzie, jak długo i kto ma do tego dostęp.
Na nim opierają się eksport danych (ZP-128), usunięcie konta (ZP-53), polityka prywatności (ZP-129)
i szyfrowanie (ZP-131).

Podstawy prawne i okresy przechowywania ustalił zespół; nie są opinią prawną.

## Gdzie są dane

| Miejsce | Co tam jest | Dane osobowe |
|---|---|---|
| PostgreSQL (`postgres_data`) | Konta, profile, pliki z odczytami, urządzenia, plany, przebiegi symulacji, cenniki | tak |
| Hub Smart Home (`hub_data`) | Rejestr urządzeń domu (`state.json`, `devices/*.json`): nazwy, typy, pomieszczenia, programy | pośrednio (nazwy urządzeń nadane przez użytkownika) |
| Przeglądarka (`localStorage`) | Tokeny sesji | tak |
| Logi kontenerów | Zapytania HTTP (adres, ścieżka, kod odpowiedzi), ostrzeżenia z `user_id` | tak (IP, id konta) |
| Zmienne środowiskowe | `HUB_HOME_USER_EMAIL`: e-mail właściciela domu Smart Home | tak |

Plików wgranych przez użytkownika nie zapisujemy w całości: parser zamienia je na odczyty i akcje urządzeń,
a z pliku zostaje tylko nazwa i metadane.

## Dane użytkownika w bazie

Wszystkie tabele z `user_id` mają `ON DELETE CASCADE`: usunięcie wiersza w `users` usuwa resztę danych konta.
Wyjątek to `home_connection`, gdzie `user_id` dostaje `NULL` (dom zostaje odłączony).

Podstawy prawne (art. 6 ust. 1 RODO): **b** – niezbędne do świadczenia usługi, o którą prosi użytkownik;
**f** – prawnie uzasadniony interes (bezpieczeństwo, diagnostyka).

| Tabela | Najważniejsze kolumny | Osobowe | Cel | Podstawa | Przechowywanie |
|---|---|---|---|---|---|
| `users` | `email`, `password_hash` (bcrypt), `provider`, `provider_id` (Google), `created_at`, `last_login_at` | tak | Logowanie i identyfikacja konta | b | Do usunięcia konta |
| `tokens` | `token_hash` (pbkdf2), `expires_at` | tak | Odświeżanie sesji; jeden wiersz na konto, nadpisywany | b | 7 dni od wydania, potem nieważny |
| `privacy_consents` | `policy_version`, `accepted_at`, `source` (rejestracja, Google, ponowna akceptacja) | tak | Dowód akceptacji polityki prywatności (ZP-129) | b | Do usunięcia konta |
| `user_profiles` | `base_info` (typ budynku, rok budowy, powierzchnia, liczba domowników, miejscowość, kod pocztowy, współrzędne domu, operator, faza, moc przyłączeniowa, cykl rozliczeń), `consumption_and_tariff`, `pv_config` (rozliczenie i panele) | tak | Rachunki taryf, plan na jutro, ceny kwadransów | b | Do usunięcia konta |
| `energy_data_files` | `file_name`, daty, liczba rekordów, `error_message` | tak | Lista wgranych plików | b | Do usunięcia pliku lub konta |
| `energy_readings` | `measured_at`, `energy_kwh`, `exported_kwh` (co 15 min) | tak | Wszystkie wyliczenia kosztów | b | Do usunięcia pliku lub konta |
| `simulations` | `results` (statystyki i wykresy pliku) | tak | Wykresy i podsumowania pliku | b | Do usunięcia pliku lub konta |
| `device_instances`, `device_programs` | Nazwy urządzeń, typ, pomieszczenie, moc, okna pracy, programy | tak | Optymalizacja, plan, symulacja | b | Do usunięcia konta |
| `device_instance_files`, `device_actions`, `device_slot_usage` | Kiedy i ile zużyło każde urządzenie | tak | Koszt per urządzenie, optymalizacja, odtwarzanie PV | b | Do usunięcia pliku lub konta |
| `planning_templates` | Ustawienia planu na jutro (godziny, programy, temperatura wody) | tak | Plan na jutro | b | Do usunięcia konta |
| `day_plans` | Plan doby z cenami i oszczędnością | tak | Plan na jutro, wykonanie w symulacji | b | Do usunięcia konta |
| `plan_runs` | Przebieg planu w symulacji, raport przed i po | tak | Raport z symulacji, historia | b | Do usunięcia konta |
| `home_events` | Zdarzenia huba: start, koniec, energia urządzeń co kwadrans | tak | Stan domu, raport przebiegu | b | Do usunięcia konta |
| `home_connection` | `user_id` właściciela domu, `connected_at`, stan wysyłki rejestru | tak | Podłączenie domu do huba | b | Do odłączenia domu |

Dlaczego dane zużycia to dane osobowe: odczyty co 15 minut przypisane do konta pokazują rytm dnia domowników
(kiedy wstają, wychodzą, wracają, czy są na urlopie). Nie są to dane szczególnej kategorii (art. 9), ale
ich wyciek jest dla użytkownika dotkliwy (patrz „Bezpieczeństwo przechowywania”).

### Dane bez danych osobowych

Cenniki i ceny rynkowe nie dotyczą użytkowników: `tariff_definitions`, `supplier_ure_rates`,
`osd_variable_network_rates`, `osd_subscription_fees`, `tariff_zone_hours`, `regulatory_periods`,
`capacity_fee_thresholds`, `transition_fee_thresholds`, `unsupported_tariffs`, ceny `rce_price_observations`
i `rcem_price_observations`, przebiegi workera `price_sync_runs`, słowniki `device_types` i `device_categories`.

Pogoda `weather_observations` też nie ma `user_id`: wiersze dotyczą komórki siatki ok. 0,1° (kilka km),
wspólnej dla domów w okolicy, i zostają po usunięciu konta.

## Kto ma dostęp

| Kto | Do czego |
|---|---|
| Użytkownik | Tylko do własnych danych przez API: każde zapytanie filtruje po `user_id` z tokenu (testy izolacji w `docs/testing.md`) |
| Właściciel domu Smart Home (`HUB_HOME_USER_EMAIL`) | Dodatkowo do huba: rejestr jego urządzeń i sterowanie symulacją |
| Hub Smart Home | Rejestr urządzeń właściciela (bez e-maila i bez odczytów), wysyła zdarzenia do backendu z kluczem API |
| Administratorzy serwera (zespół) | Pełny dostęp do bazy, wolumenów i logów |

## Podmioty zewnętrzne

| Podmiot | Co dostaje | Kiedy |
|---|---|---|
| Google (OAuth) | Token logowania; od Google dostajemy e-mail i identyfikator konta | Logowanie przez Google |
| Google (skrypt logowania) | Adres IP przeglądarki: `@react-oauth/google` pobiera skrypt z `accounts.google.com` | Tylko na ekranie logowania i rejestracji |
| PSE (`api.raporty.pse.pl`, `pse.pl`) | Nic o użytkownikach: pobieramy publiczne ceny RCE i RCEm | Worker cen, codziennie |
| OpenStreetMap Nominatim (`nominatim.openstreetmap.org`) | Kod pocztowy, a gdy go nie zna, nazwa miejscowości (wyznaczenie współrzędnych); bez danych konta | Zapis profilu po zmianie adresu i pierwszy odczyt profilu bez współrzędnych |
| Open-Meteo (`api.open-meteo.com`, `archive-api.open-meteo.com`) | Współrzędne domu zaokrąglone do 0,1° oraz kierunek i nachylenie paneli; bez danych konta | Worker pogody co 3 h, po imporcie pliku, po zapisie profilu i przy odczycie pogody, której nie ma w bazie |

Żadnemu podmiotowi zewnętrznemu nie przekazujemy odczytów zużycia, profilu ani e-maila.

## Minimalizacja

Każde pole profilu ma cel:

| Pole | Cel |
|---|---|
| `town`, `postal_code` | Lokalizacja domu do prognozy pogody i produkcji PV. Kod pocztowy rozróżnia miejscowości o tej samej nazwie. Do Nominatim idą tylko przy wyznaczaniu współrzędnych |
| `location` | Współrzędne domu (dokładność obszaru kodu pocztowego albo położenie z przeglądarki, gdy użytkownik je wskaże); tylko one idą do Open-Meteo |
| `pv_config.installation` | Moc, kierunek i nachylenie grup paneli oraz moc falownika: prognoza produkcji PV i opust net-meteringu |
| `year_of_construction`, `heating_area_m2`, `type_of_property` | Straty ciepła budynku: zużycie pompy ciepła zależne od temperatury |
| `number_of_residents` | Domyślna pojemność bojlera i zużycie ciepłej wody |
| `contracted_power_kw`, `phase_type`, operator, cykl rozliczeń, taryfa, PV | Rachunki taryf, ceny kwadransów i limit przyłącza w planie |

Poza profilem:

- `simulations.results` trzyma statystyki i wykresy pliku, bez cen. Ceny kwadransów liczymy przy odczycie
  z cennika, a seria zużycia jest tylko w `energy_readings`.
- Przeglądarka trzyma w `localStorage` tylko tokeny sesji. Dane zalogowanego użytkownika frontend pobiera
  z `/users/me`.
- Skrypt logowania Google ładuje się tylko na ekranach logowania i rejestracji, więc Google nie widzi wizyt
  zalogowanych użytkowników.
- Logi zawierają `user_id`, ale nie e-maile ani treść plików.

## Retencja

Projekt jest PoC: nie ma automatycznego czyszczenia danych ani kopii zapasowych. Dane konta są przechowywane
do jego usunięcia (kaskada w bazie), a odczyty pliku do usunięcia pliku lub konta.

| Dane | Reguła |
|---|---|
| Konto i dane w tabelach z `user_id` | Do usunięcia konta przez użytkownika |
| Pliki z odczytami (`energy_data_files` i zależne) | Do usunięcia pliku lub konta |
| `tokens` | Jeden wiersz na konto, nadpisywany przy logowaniu, nieważny po 7 dniach |
| Logi kontenerów | Domyślne ustawienia Dockera, bez skonfigurowanej rotacji |

## Prawa użytkownika

- **Dostęp i przenoszenie danych:** w aplikacji nie ma eksportu; obsługujemy je na prośbę wysłaną e-mailem.
- **Usunięcie konta:** usuwa wiersz w `users`, a kaskady resztę danych. Gdy konto jest właścicielem domu Smart
  Home, backend wysyła do huba pusty rejestr. Frontend czyści `localStorage`.
- **Sprostowanie:** profil i urządzenia użytkownik zmienia sam w aplikacji (profil, ponowny import pliku).

## Bezpieczeństwo przechowywania

Najbardziej wrażliwe są odczyty zużycia i akcje urządzeń. W PoC nie szyfrujemy wolumenu bazy ani kolumn;
ochronę zapewnia izolacja danych po `user_id` i dostęp do serwera tylko dla zespołu. Hasła są przechowywane
jako skróty bcrypt, a refresh tokeny jako skróty pbkdf2.

## Polityka prywatności

Treść polityki dla użytkowników jest w `backend/app/legal/privacy_policy.md`, a jej wersja (data publikacji)
w `PRIVACY_POLICY_VERSION` w `backend/app/services/privacy_policy.py`. Po każdej zmianie treści trzeba podbić
wersję: użytkownicy z akceptacją starszej wersji zobaczą przy najbliższym wejściu okno ponownej akceptacji.
Zmiany w tym dokumencie, które dotyczą użytkowników, trzeba przenieść także do polityki.
