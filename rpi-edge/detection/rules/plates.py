"""Polish plate format check: rejects OCR output that cannot be a Polish registration number.

The rules and their legal source are in ml-models/PLATE_FORMAT.md (the registration regulation, Dz.U. 2022
poz. 1847 with the amendment Dz.U. 2023 poz. 1255). Two kinds of plates pass, as decided for the send rule:

  ordinary    voivodeship letter + county code (annex 13) + vehicle part in one of the layouts of
              par. 30 ust. 2 pkt 1; one- and two-row car plates carry the same numbers
  individual  voivodeship letter + digit + 3 to 5 characters chosen by the owner (par. 30 ust. 2 pkt 4)

Reduced, motorcycle, moped, temporary, historic and diplomatic plates fail, as do plates of the services
(army, police), which the regulation does not cover. Keep this module and PLATE_FORMAT.md in step.
"""
import re

LETTERS = "ABCDEFGHIJKLMNOPRSTUVWXYZ"  # the 25 letters of par. 30 ust. 1: no Q
# Par. 31 ust. 1: the vehicle part of an ordinary plate never uses B, D, I, O, Z.
VEHICLE_PART_LETTERS = "ACEFGHJKLMNPRSTUVWXY"

# Annex 13: the voivodeship letters (column 4) and the county codes (column 5) of each voivodeship.
COUNTY_CODES = {
    "DV": "J L B W X BL DZ GL GR JA JE KA KL LE LB LU LW MI OL OA PL ST SR SW TR BA WL WR ZA ZG ZL",  # dolnośląskie
    "C": "B G T W AL BR BY CH GD GR IN LI MG NA RA RY SE SW TR TU WA WL ZN",  # kujawsko-pomorskie
    "L": "B C U Z BI BL CH HR JA KS KR LB UB LE LU OP PA PU RA RY SW TM WL ZA",  # lubelskie
    "F": "G Z GW KR MI NW SL SD SU SW WS ZI ZG ZA",  # lubuskie
    "E": "L D P S BR BE KU LA LE LC LW OP PA PJ PI PD RA RW SI SK TM WI WE ZD ZG",  # łódzkie
    "KJ": "R K N T BC BA BR CH DA GR RA RK LI MI MY NS NT OL OS PR SU TA TT WA WI",  # małopolskie
    "WA": "O P R S BR CI G GS GM GR KZ L LI LS MA M ML ND OS OR OT PI PA PW PX PL PN PR PP PS PZ PY PU RA SI "
          "SE SC SK SZ A B D E F H I J K N T U W X Y Z WE WL V WY ZW ZU ZY",  # mazowieckie
    "O": "P B GL K KL KR NA NY OL PO PR ST",  # opolskie
    "RY": "K P Z T BI BR DE JA JS KL KR LS LE LU LA MI NI PR PZ RS ZE ZZ ZR SA ST SR TA",  # podkarpackie
    "B": "I L S AU IA IB BI GR HA KL LM MN SE SI SK SU WM ZA",  # podlaskie
    "GX": "D A S SP BY CH CZ DA KA KY KZ KS KW LE MB ND PU SL ST SZ TC WE WO",  # pomorskie
    "SI": "B Y H C D G JZ J K M PI RS L R I O W T Z ZO BE E BN BI CI CN CZ GL KL LU MI MY PS RC RB TA BL WD "
          "WZ ZA ZY",  # śląskie
    "T": "K BU JE KA KI KN OP OS PI SA SK ST SZ LW",  # świętokrzyskie
    "N": "E O BA BR DZ EB EL GI IL KE LI MR NI NM OE GO OL OS PI SZ WE",  # warmińsko-mazurskie
    "PM": "K A KO N L O Y CH CT GN GS GO JA KA KE KL KN KS KR LE MI NT OB OS OT P PL OZ Z RA SL SZ SR SE TU WA "
          "WL WR ZL",  # wielkopolskie
    "Z": "K S Z SW BI CH DR GL GY GR KA KL KO LO MY PL PY SL ST SZ SD WA",  # zachodniopomorskie
}

# Par. 30 ust. 2 pkt 1, D = digit, L = letter. Every run of digits lies in a range that excludes zero
# (00001-99999, 0001-9999, 001-999, 01-99, 1-9), so no run may be all zeros.
AFTER_ONE_LETTER_COUNTY = ("DDDDD", "DDDDL", "DDDLL", "DLDDD", "DLLDD")
AFTER_TWO_LETTER_COUNTY = ("LDDD", "DDLL", "DLDD", "DDLD", "DLLD", "LLDD", "DDDDD", "DDDDL", "DDDLL")


def _layout(shape: str) -> str:
    """'DLLDD' -> a regex in which every run of digits is not all zeros."""
    parts = []
    for run in re.findall(r"D+|L+", shape):
        n = len(run)
        parts.append(f"(?!0{{{n}}})[0-9]{{{n}}}" if run[0] == "D" else f"[{VEHICLE_PART_LETTERS}]{{{n}}}")
    return "".join(parts)


def _any_of(options) -> str:
    return "(?:" + "|".join(sorted(options)) + ")"


def _prefixes(county_length: int) -> set[str]:
    return {voivodeship + county for voivodeships, codes in COUNTY_CODES.items()
            for voivodeship in voivodeships for county in codes.split() if len(county) == county_length}


_VOIVODESHIPS = "".join(sorted(set("".join(COUNTY_CODES))))
_ORDINARY = re.compile(
    _any_of(_prefixes(1)) + _any_of(map(_layout, AFTER_ONE_LETTER_COUNTY))
    + "|" + _any_of(_prefixes(2)) + _any_of(map(_layout, AFTER_TWO_LETTER_COUNTY)))
# Par. 30 ust. 2 pkt 4: 3 to 5 letters, of which at most the last two may be replaced by a number.
_INDIVIDUAL = re.compile(
    f"[{_VOIVODESHIPS}][0-9](?:[{LETTERS}]{{3,5}}|[{LETTERS}]{{2,4}}[0-9]|[{LETTERS}]{{1,3}}[0-9]{{2}})")


def is_polish_plate(text: str) -> bool:
    """True when the text can be an ordinary or an individual Polish registration number."""
    return _ORDINARY.fullmatch(text) is not None or _INDIVIDUAL.fullmatch(text) is not None
