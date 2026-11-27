from fakes import FakeApi, response
from samples import configuration

from common.faults import FaultBoard
from detection.cloud.alert_poll import AlertPoller
from detection.cloud.transport import NetworkError
from detection.rules.alerts import AlertWatch

URL = "https://abc.execute-api.eu-central-1.amazonaws.com/api/v1/alerts"
ALERT = {"alertId": "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c", "plate": "WA12345", "alertText": None,
         "createdAt": "2026-11-01T10:00:00Z", "version": 1}


class FixedConfiguration:
    current = configuration()


def test_the_list_is_replaced_and_polled_with_its_etag():
    watch = AlertWatch()
    api = FakeApi(response(200, {"items": [ALERT], "page": {}}, {"ETag": 'W/"7"'}), response(304))
    poller = AlertPoller(api, URL, watch, FixedConfiguration(), FaultBoard())
    assert not watch.loaded
    poller.poll_once()
    assert watch.loaded and len(watch) == 1 and watch.match("WA12345").alert_id == ALERT["alertId"]
    poller.poll_once()
    assert "If-None-Match" not in api.requests[0]["headers"]
    assert api.requests[1]["headers"]["If-None-Match"] == 'W/"7"'


def test_failures_and_invalid_lists_keep_the_current_list():
    watch = AlertWatch()
    api = FakeApi(response(200, {"items": [ALERT]}, {"ETag": '"1"'}), NetworkError("offline"), response(500),
                  response(200, {"items": [ALERT | {"plate": "not a plate"}]}, {"ETag": '"2"'}))
    poller = AlertPoller(api, URL, watch, FixedConfiguration(), FaultBoard())
    for _ in range(4):
        poller.poll_once()
    assert watch.match("WA12345") is not None and watch.etag == '"1"'


def test_error_answers_in_a_row_are_a_fault_until_a_list_is_taken_and_no_answer_is_none():
    faults = FaultBoard()
    answers = (NetworkError("offline"), response(500), response(503), response(500),
               response(200, {"items": [{"plate": 1}]}), response(304))
    poller = AlertPoller(FakeApi(*answers), URL, AlertWatch(), FixedConfiguration(), faults)
    texts = []
    for _ in answers:
        poller.poll_once()
        texts.append([f.text for f in faults.active()])
    assert texts == [[], [], [], ["alert list failed"], ["alert list invalid"], []]


def test_a_device_without_an_owner_is_the_account_fault_not_a_failing_list():
    faults = FaultBoard()
    no_owner = response(403, {"code": "DEVICE_NOT_PAIRED"})
    poller = AlertPoller(FakeApi(no_owner, no_owner, no_owner), URL, AlertWatch(), FixedConfiguration(), faults)
    for _ in range(3):
        poller.poll_once()
    assert faults.active() == []  # Api shows "device has no owner"


def test_an_unknown_plate_is_no_alert():
    assert AlertWatch().match("WA12345") is None
