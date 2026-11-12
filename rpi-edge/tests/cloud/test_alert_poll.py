from fakes import FakeApi, response
from samples import configuration

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
    poller = AlertPoller(api, URL, watch, FixedConfiguration())
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
    poller = AlertPoller(api, URL, watch, FixedConfiguration())
    for _ in range(4):
        poller.poll_once()
    assert watch.match("WA12345") is not None and watch.etag == '"1"'


def test_an_unknown_plate_is_no_alert():
    assert AlertWatch().match("WA12345") is None
