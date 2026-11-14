import json

from detection.contract.problem import FieldError, Problem


def test_a_problem_document_gives_its_code_and_field_errors():
    body = json.dumps({"type": "about:blank", "status": 400, "code": "VALIDATION_FAILED", "fields": [
        {"index": 1, "field": "detections[1].plate", "code": "PATTERN"},
        {"field": "batchId", "code": "REQUIRED"}]}).encode()
    problem = Problem.of(400, body)
    assert problem.code == "VALIDATION_FAILED"
    assert problem.fields[0] == FieldError(1, "detections[1].plate", "PATTERN")
    assert problem.indexes == {1}


def test_any_other_body_gives_an_empty_problem():
    for body in (b"", b"<html>Bad Gateway</html>", b"[1]", json.dumps({"code": 7}).encode()):
        problem = Problem.of(502, body)
        assert problem.code is None and problem.fields == () and problem.status == 502
