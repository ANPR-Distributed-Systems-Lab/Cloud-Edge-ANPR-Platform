import pytest

from detection.contract.alerts import Alert, AlertList
from detection.contract.parsing import ContractError

ALERT_ID = "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c"


def item(**override):
    return {"alertId": ALERT_ID, "plate": "WA12345", "alertText": "Stolen", "createdAt": "2026-11-01T10:00:00Z",
            "lastDetectedAt": None, "version": 2} | override


def test_the_page_maps_onto_alerts_and_ignores_what_the_device_does_not_need():
    page = {"items": [item(), item(plate="KR1AC23", alertText=None)], "page": {"page": 0, "size": 2}}
    alerts = AlertList.from_document(page)
    assert alerts.items == (Alert(ALERT_ID, "WA12345", "Stolen"), Alert(ALERT_ID, "KR1AC23", None))


def test_an_empty_list_is_valid():
    assert AlertList.from_document({"items": [], "page": {}}).items == ()


@pytest.mark.parametrize("override, problem", [
    ({"plate": "wa 12345"}, "items[0].plate must match"),
    ({"alertId": "x"}, "items[0].alertId must match"),
    ({"alertText": 5}, "items[0].alertText must match"),
])
def test_alerts_outside_the_contract_are_named(override, problem):
    with pytest.raises(ContractError) as e:
        AlertList.from_document({"items": [item(**override)]})
    assert any(p.startswith(problem) for p in e.value.problems)
