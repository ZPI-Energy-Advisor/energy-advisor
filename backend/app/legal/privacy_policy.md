# Polityka prywatności Energy Advisor

Ten dokument wyjaśnia, jakie dane osobowe zbiera Energy Advisor, po co, jak długo je przechowujemy i jakie
masz prawa (art. 13 RODO).

## Administrator danych

Administratorem danych jest Zespół projektu Energy Advisor (ZPI, Politechnika Wrocławska).
W sprawach danych osobowych napisz na adres **energy-advisor@gmail.com**.
Nie powołaliśmy inspektora ochrony danych.

## Jakie dane zbieramy i po co

- **Dane konta:** adres e-mail, skrót hasła (bcrypt) albo identyfikator konta Google, data założenia konta
  i ostatniego logowania. Służą do logowania i identyfikacji konta.
- **Profil domu:** typ i rok budowy budynku, powierzchnia ogrzewana, liczba domowników, miejscowość, kod
  pocztowy, przybliżone współrzędne domu, operator sieci, faza, moc przyłączeniowa, cykl rozliczeń, taryfa
  i instalacja fotowoltaiczna. Służą do wyliczania rachunków, porównania taryf i planu zużycia na następny dzień.
- **Odczyty zużycia energii** z wgranych plików (co 15 minut) oraz statystyki i wykresy pliku. Sam plik nie
  jest przechowywany: zostaje jego nazwa i odczyty.
- **Urządzenia i plany:** nazwy, typy, pomieszczenia i programy urządzeń, ustawienia planu dnia, plany
  i przebiegi symulacji. Służą do optymalizacji zużycia i raportów.
- **Dane techniczne:** adres IP, adres zapytania i kod odpowiedzi w logach serwera. Służą do zapewnienia
  bezpieczeństwa i diagnozowania błędów.
- **Dane sesji w przeglądarce:** tokeny logowania, niezbędne do utrzymania zalogowania. Nie używamy cookies
  ani narzędzi analitycznych i reklamowych.

Odczyty zużycia co 15 minut pokazują rytm dnia domowników, dlatego traktujemy je jako dane osobowe i chronimy
tak jak pozostałe dane konta.

## Podstawa prawna

- **Art. 6 ust. 1 lit. b RODO** – przetwarzanie jest niezbędne do świadczenia usługi, o którą prosisz
  (konto, profil, odczyty, urządzenia, plany).
- **Art. 6 ust. 1 lit. f RODO** – nasz prawnie uzasadniony interes: bezpieczeństwo aplikacji i diagnozowanie
  błędów (logi serwera).

Podanie danych jest dobrowolne, ale bez adresu e-mail nie da się założyć konta, a bez profilu domu i odczytów
aplikacja nie wyliczy rachunków ani planu.

## Jak długo przechowujemy dane

- **Konto i wszystkie jego dane:** do usunięcia konta. Usunięcie konta w profilu usuwa od razu wszystkie
  powiązane z nim dane.
- **Pliki z odczytami:** do usunięcia pliku lub konta.
- **Sesja logowania:** token odświeżania jest ważny 7 dni; przy kolejnym logowaniu zastępuje go nowy.

## Komu przekazujemy dane

Nie sprzedajemy danych i nie przekazujemy nikomu odczytów zużycia, profilu domu ani adresu e-mail.
Korzystamy z następujących usług zewnętrznych:

- **Google** – przy logowaniu przez Google otrzymujemy od Google adres e-mail i identyfikator konta. Skrypt
  logowania Google ładuje się tylko na ekranie logowania i rejestracji, więc Google widzi wtedy adres IP
  przeglądarki.
- **OpenStreetMap Nominatim** – kod pocztowy lub nazwa miejscowości (bez danych konta) do wyznaczenia
  współrzędnych domu.
- **Open-Meteo** – same współrzędne domu (bez danych konta) do prognozy pogody i produkcji fotowoltaiki.

Dostęp do serwera, bazy i logów ma wyłącznie zespół projektu.
Dane nie są przekazywane poza Europejski Obszar Gospodarczy, z wyjątkiem logowania przez Google, które
odbywa się na zasadach Google.

## Twoje prawa

Masz prawo do:

- **dostępu do danych** i otrzymania ich kopii,
- **sprostowania danych** – profil i urządzenia zmienisz sam w aplikacji,
- **usunięcia danych** – konto ze wszystkimi danymi usuniesz w profilu,
- **ograniczenia przetwarzania**,
- **przenoszenia danych**,
- **sprzeciwu** wobec przetwarzania opartego na prawnie uzasadnionym interesie.

Aby skorzystać z praw, których nie obsłużysz sam w aplikacji, napisz na **energy-advisor@gmail.com**.
Masz też prawo wnieść skargę do **Prezesa Urzędu Ochrony Danych Osobowych** (ul. Stawki 2, 00-193 Warszawa).

## Zautomatyzowane decyzje

Aplikacja wylicza rachunki, porównuje taryfy i proponuje plan zużycia, ale nie podejmuje wobec Ciebie decyzji
wywołujących skutki prawne ani w podobny sposób istotnie na Ciebie wpływających (art. 22 RODO). Wyniki są
wyłącznie podpowiedzią.

## Bezpieczeństwo

Hasła przechowujemy jako skróty bcrypt, a tokeny odświeżania sesji jako skróty pbkdf2. Każde zapytanie do aplikacji zwraca wyłącznie dane zalogowanego
użytkownika.

## Zmiany polityki

Gdy zmienimy tę politykę, przy najbliższym logowaniu poprosimy o zapoznanie się z nową wersją i jej akceptację.
Datę bieżącej wersji widać na górze strony polityki.
