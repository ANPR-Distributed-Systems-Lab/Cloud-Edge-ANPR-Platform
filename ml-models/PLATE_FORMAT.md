# Polish registration numbers: the per-position rules

What a Polish registration number may look like, written down from the legal text. The send rule on the Pi
(`rpi-edge/detection/rules/plates.py`) implements it; the final OCR model can use it for per-position rules
(ML_ASSUMPTIONS.md, section 7). Keep the two in step.

## Source and verification

- **Rozporządzenie Ministra Infrastruktury z dnia 31 sierpnia 2022 r. w sprawie rejestracji i oznaczania
  pojazdów, wymagań dla tablic rejestracyjnych oraz wzorów innych dokumentów związanych z rejestracją pojazdów**
  (Dz.U. 2022 poz. 1847): § 27 (what a number consists of), § 30 (letters, digits and layouts), § 31 (letters
  not used, annex 13), § 32 (individual plates), annex 13 (voivodeship and county codes).
- **Amendment** of 2023 (Dz.U. 2023 poz. 1255, in force since 2023-07-01), § 1 pkt 6: second letters of the
  voivodeship code for temporary and individual plates (column 6 of annex 13).
- Read from the official PDFs of eli.gov.pl on 2026-11-12. Annex 13 was extracted from the PDF and compared
  entry by entry with the code: 16 voivodeships, 380 counties (the number of Polish counties), 421 county codes.
  No later amendment touching § 30, § 31 or annex 13 was found; check eli.gov.pl before relying on this
  document in a new year.

## Scope (decided 2026-11-12)

The format check accepts two kinds of plates:

| Kind | Rule | Why |
|---|---|---|
| Ordinary car plates (one-row and two-row) | § 30 ust. 2 pkt 1 | Almost all cars on the road; the whole OCR dataset (`type: standard`) |
| Individual plates | § 30 ust. 2 pkt 4 | Seen on the road; still a narrow shape (letter, digit, then letters) |

Not accepted: reduced one-row car plates, motorcycle and moped plates, temporary, historic and diplomatic
plates (each has its own layouts in § 30 ust. 2 pkt 2, 3, 5, 6, 7), and the plates of the army and the
services, which this regulation does not define. Plates issued under earlier regulations and still valid
are not covered by this document either.

## Characters (§ 30 ust. 1, § 31 ust. 1)

- 25 letters: `A B C D E F G H I J K L M N O P R S T U V W X Y Z`. **Q never appears.** Digits `0`-`9`.
- The vehicle part of an ordinary plate never uses **B, D, I, O, Z** (§ 31 ust. 1), so it uses 20 letters:
  `A C E F G H J K L M N P R S T U V W X Y`. The exclusion does not apply to the individual part of an
  individual plate, which the owner chooses (§ 32 ust. 2).
- For OCR: in the vehicle part, a read `O` can only be `0`, `I` only `1`, `B` only `8`, `Z` only `2`, `D` only
  `0`. In the voivodeship and county codes the opposite holds: only letters.

## Ordinary car plates (§ 27 ust. 2, § 30 ust. 2 pkt 1)

Number = **voivodeship letter** + **county code** (1 or 2 letters) + **vehicle part**. The voivodeship letter is
the first letter, the county code the second, or the second and third (annex 13; the pair of letters is a fixed
combination, not any letter from each list). One- and two-row plates carry the same number.

Vehicle part, D = digit, L = letter of the 20 above. The regulation gives each run of digits a range:

| County code | Layout | Ranges in the regulation | Length of the number |
|---|---|---|---|
| 1 letter (`WA`, `KR`, ...) | DDDDD | 00001-99999 | 7 |
| | DDDDL | 0001-9999, letter | 7 |
| | DDDLL | 001-999, 2 letters | 7 |
| | DLDDD | 1-9, letter, 001-999 | 7 |
| | DLLDD | 1-9, 2 letters, 01-99 | 7 |
| 2 letters (`WPI`, `KRA`, ...) | LDDD | letter, 001-999 | 7 |
| | DDLL | 01-99, 2 letters | 7 |
| | DLDD | 1-9, letter, 01-99 | 7 |
| | DDLD | 01-99, letter, 1-9 | 7 |
| | DLLD | 1-9, 2 letters, 1-9 | 7 |
| | LLDD | 2 letters, 01-99 | 7 |
| | DDDDD | 00001-99999 | 8 |
| | DDDDL | 0001-9999, letter | 8 |
| | DDDLL | 001-999, 2 letters | 8 |

Every range excludes zero: a run of digits is never all zeros, and a single digit is 1-9.

A text can fit both a 1-letter and a 2-letter county code (`WP` Płock and `WPI` piaseczyński); it is a valid
number when either reading fits.

## Individual plates (§ 27 ust. 4, § 30 ust. 2 pkt 4, § 32)

Number = **voivodeship letter** + **digit** (column 6 of annex 13: `W0`-`W9`, ...; since 2023 also the second
letters `V`, `J`, `A`, `Y`, `X`, `I`, `M`, the same as the letters of column 4) + **3 to 5 letters** chosen by the
owner, of which **at most the last two may be replaced by a number**. So the individual part is one of:
3-5 letters; 2-4 letters and a digit; 1-3 letters and two digits. Length of the number: 5 to 7. The regulation
gives no range for that number, so any digits are accepted.

## Annex 13: voivodeship and county codes

Column 4 holds the voivodeship letters of ordinary, historic and diplomatic plates; where there are two, numbers
with the second letter are issued once the first is exhausted (§ 31 ust. 3), and every county code combines with
both. Column 5 holds the county codes, column 6 the voivodeship codes of temporary and individual plates (with the
2023 amendment).

| Lp. | Voivodeship | Letters (col. 4) | Individual (col. 6) | County codes (col. 5), with the county |
|---|---|---|---|---|
| 1 | dolnośląskie | D, V | D0–D9, V0–V9 | J Jelenia Góra; L Legnica; B Wałbrzych; W, X Wrocław; BL bolesławiecki; DZ dzierżoniowski; GL głogowski; GR górowski; JA jaworski; JE karkonoski; KA kamiennogórski; KL kłodzki; LE legnicki; LB lubański; LU lubiński; LW lwówecki; MI milicki; OL oleśnicki; OA oławski; PL polkowicki; ST strzeliński; SR średzki; SW świdnicki; TR trzebnicki; BA wałbrzyski; WL wołowski; WR wrocławski; ZA ząbkowicki; ZG zgorzelecki; ZL złotoryjski |
| 2 | kujawsko-pomorskie | C | C0–C9 | B Bydgoszcz; G Grudziądz; T Toruń; W Włocławek; AL aleksandrowski; BR brodnicki; BY bydgoski; CH chełmiński; GD golubsko-dobrzyński; GR grudziądzki; IN inowrocławski; LI lipnowski; MG mogileński; NA nakielski; RA radziejowski; RY rypiński; SE sępoleński; SW świecki; TR toruński; TU tucholski; WA wąbrzeski; WL włocławski; ZN żniński |
| 3 | lubelskie | L | L0–L9 | B Biała Podlaska; C Chełm; U Lublin; Z Zamość; BI bialski; BL biłgorajski; CH chełmski; HR hrubieszowski; JA janowski; KS krasnostawski; KR kraśnicki; LB lubartowski; UB lubelski; LE łęczyński; LU łukowski; OP opolski; PA parczewski; PU puławski; RA radzyński; RY rycki; SW świdnicki; TM tomaszowski; WL włodawski; ZA zamojski |
| 4 | lubuskie | F | F0–F9 | G Gorzów Wielkopolski; Z Zielona Góra; GW gorzowski; KR krośnieński; MI międzyrzecki; NW nowosolski; SL słubicki; SD strzelecko-drezdenecki; SU sulęciński; SW świebodziński; WS wschowski; ZI zielonogórski; ZG żagański; ZA żarski |
| 5 | łódzkie | E | E0–E9 | L, D Łódź; P Piotrków Trybunalski; S Skierniewice; BR brzeziński; BE bełchatowski; KU kutnowski; LA łaski; LE łęczycki; LC łowicki; LW łódzki wschodni; OP opoczyński; PA pabianicki; PJ pajęczański; PI piotrkowski; PD poddębicki; RA radomszczański; RW rawski; SI sieradzki; SK skierniewicki; TM tomaszowski; WI wieluński; WE wieruszowski; ZD zduńskowolski; ZG zgierski |
| 6 | małopolskie | K, J | K0–K9, J0–J9 | R, K Kraków; N Nowy Sącz; T Tarnów; BC, BA bocheński; BR brzeski; CH chrzanowski; DA dąbrowski; GR gorlicki; RA, RK krakowski; LI limanowski; MI miechowski; MY myślenicki; NS nowosądecki; NT nowotarski; OL olkuski; OS oświęcimski; PR proszowicki; SU suski; TA tarnowski; TT tatrzański; WA wadowicki; WI wielicki |
| 7 | mazowieckie | W, A | W0–W9, A0–A9 | O Ostrołęka; P Płock; R Radom; S Siedlce; BR białobrzeski; CI ciechanowski; G garwoliński; GS gostyniński; GM grodziski; GR grójecki; KZ kozienicki; L legionowski; LI lipski; LS łosicki; MA makowski; M miński; ML mławski; ND nowodworski; OS ostrołęcki; OR ostrowski; OT otwocki; PI, PA, PW, PX piaseczyński; PL płocki; PN płoński; PR, PP, PS pruszkowski; PZ przasnyski; PY przysuski; PU pułtuski; RA radomski; SI siedlecki; SE sierpecki; SC sochaczewski; SK sokołowski; SZ szydłowiecki; A, B, D, E, F, H, I, J, K, N, T, U, W, X, Y m.st. Warszawa; Z warszawski zachodni; WE węgrowski; WL, V wołomiński; WY wyszkowski; ZW zwoleński; ZU żuromiński; ZY żyrardowski |
| 8 | opolskie | O | O0–O9 | P Opole; B brzeski; GL głubczycki; K kędzierzyńsko-kozielski; KL kluczborski; KR krapkowicki; NA namysłowski; NY nyski; OL oleski; PO opolski; PR prudnicki; ST strzelecki |
| 9 | podkarpackie | R, Y | R0–R9, Y0–Y9 | K Krosno; P Przemyśl; Z Rzeszów; T Tarnobrzeg; BI bieszczadzki; BR brzozowski; DE dębicki; JA jarosławski; JS jasielski; KL kolbuszowski; KR krośnieński; LS leski; LE leżajski; LU lubaczowski; LA łańcucki; MI mielecki; NI niżański; PR przemyski; PZ przeworski; RS ropczycko-sędziszowski; ZE, ZZ, ZR rzeszowski; SA sanocki; ST stalowowolski; SR strzyżowski; TA tarnobrzeski |
| 10 | podlaskie | B | B0–B9 | I Białystok; L Łomża; S Suwałki; AU augustowski; IA, IB białostocki; BI bielski; GR grajewski; HA hajnowski; KL kolneński; LM łomżyński; MN moniecki; SE sejneński; SI siemiatycki; SK sokólski; SU suwalski; WM wysokomazowiecki; ZA zambrowski |
| 11 | pomorskie | G, X | G0–G9, X0–X9 | D Gdańsk; A Gdynia; S Słupsk; SP Sopot; BY bytowski; CH chojnicki; CZ człuchowski; DA gdański; KA, KY, KZ kartuski; KS kościerski; KW kwidzyński; LE lęborski; MB malborski; ND nowodworski; PU pucki; SL słupski; ST starogardzki; SZ sztumski; TC tczewski; WE, WO wejherowski |
| 12 | śląskie | S, I | S0–S9, I0–I9 | B Bielsko-Biała; Y Bytom; H Chorzów; C Częstochowa; D Dąbrowa Górnicza; G Gliwice; JZ Jastrzębie-Zdrój; J Jaworzno; K Katowice; M Mysłowice; PI Piekary Śląskie; RS, L Ruda Śląska; R Rybnik; I Siemianowice Śląskie; O Sosnowiec; W Świętochłowice; T Tychy; Z Zabrze; ZO Żory; BE, E, BN będziński; BI bielski; CI, CN cieszyński; CZ częstochowski; GL gliwicki; KL kłobucki; LU lubliniecki; MI mikołowski; MY myszkowski; PS pszczyński; RC raciborski; RB rybnicki; TA tarnogórski; BL bieruńsko-lędziński; WD, WZ wodzisławski; ZA zawierciański; ZY żywiecki |
| 13 | świętokrzyskie | T | T0–T9 | K Kielce; BU buski; JE jędrzejowski; KA kazimierski; KI kielecki; KN konecki; OP opatowski; OS ostrowiecki; PI pińczowski; SA sandomierski; SK skarżyski; ST starachowicki; SZ staszowski; LW włoszczowski |
| 14 | warmińsko-mazurskie | N | N0–N9 | E Elbląg; O Olsztyn; BA bartoszycki; BR braniewski; DZ działdowski; EB elbląski; EL ełcki; GI giżycki; IL iławski; KE kętrzyński; LI lidzbarski; MR mrągowski; NI nidzicki; NM nowomiejski; OE olecki; GO gołdapski; OL olsztyński; OS ostródzki; PI piski; SZ szczycieński; WE węgorzewski |
| 15 | wielkopolskie | P, M | P0–P9, M0–M9 | K, A Kalisz; KO, N Konin; L Leszno; O, Y Poznań; CH chodzieski; CT czarnkowsko-trzcianecki; GN gnieźnieński; GS gostyński; GO grodziski; JA jarociński; KA kaliski; KE kępiński; KL kolski; KN koniński; KS kościański; KR krotoszyński; LE leszczyński; MI międzychodzki; NT nowotomyski; OB obornicki; OS ostrowski; OT ostrzeszowski; P pilski; PL pleszewski; OZ, Z poznański; RA rawicki; SL słupecki; SZ szamotulski; SR średzki; SE śremski; TU turecki; WA wągrowiecki; WL wolsztyński; WR wrzesiński; ZL złotowski |
| 16 | zachodniopomorskie | Z | Z0–Z9 | K Koszalin; S, Z Szczecin; SW Świnoujście; BI białogardzki; CH choszczeński; DR drawski; GL goleniowski; GY gryficki; GR gryfiński; KA kamieński; KL kołobrzeski; KO koszaliński; LO łobeski; MY myśliborski; PL policki; PY pyrzycki; SL sławieński; ST stargardzki; SZ szczecinecki; SD świdwiński; WA wałecki |

## Checked against the labeled texts (2026-11-12)

Of the 415 texts labeled so far (243 distinct plates, train_001, train_002, val_001, val_002), 412 pass. The other
three, by shape only:

- a 3-letter code with layout DDLD whose last digit is 0, outside the range 1-9: either a labeling error or a plate
  issued under an earlier regulation;
- a 3-letter code followed by DLDL, which is no layout of § 30;
- a prefix that is in no row of annex 13 (4 letters and 3 digits): a plate outside the scope above.
