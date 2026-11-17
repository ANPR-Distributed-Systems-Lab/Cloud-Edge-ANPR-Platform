"""Unit tests of create_user.py. Cognito is replaced by botocore's Stubber: no AWS access.

    pip install -r ../lambdas/event_ingest/requirements-dev.txt && pytest test_create_user.py
"""

import boto3
import pytest
from botocore.stub import Stubber

import create_user

POOL_ID = "eu-central-1_test"
SUB = "d1c2a0f8-0000-4000-8000-000000000000"
KEY = {"UserPoolId": POOL_ID, "Username": "alice"}


@pytest.fixture
def cognito():
    client = boto3.client("cognito-idp", region_name="eu-central-1", aws_access_key_id="test", aws_secret_access_key="test")
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


def expect_create(stub):
    stub.add_response(
        "admin_create_user",
        {"User": {"Username": "alice", "Attributes": [{"Name": "sub", "Value": SUB}]}},
        {**KEY, "MessageAction": "SUPPRESS"},
    )


def test_creates_a_person_with_a_permanent_password_in_the_group_of_users(cognito):
    client, stub = cognito
    expect_create(stub)
    stub.add_response("admin_set_user_password", {}, {**KEY, "Password": "Secret-password-1", "Permanent": True})
    stub.add_response("admin_add_user_to_group", {}, {**KEY, "GroupName": "users"})

    assert create_user.create_person(client, POOL_ID, "alice", "Secret-password-1") == SUB


def test_a_weak_password_deletes_the_half_created_user(cognito):
    client, stub = cognito
    expect_create(stub)
    stub.add_client_error("admin_set_user_password", service_error_code="InvalidPasswordException",
                          service_message="Password did not conform with policy")
    stub.add_response("admin_delete_user", {}, KEY)

    with pytest.raises(create_user.AccountError, match="policy"):
        create_user.create_person(client, POOL_ID, "alice", "weak")


def test_a_taken_username_creates_nothing(cognito):
    client, stub = cognito
    stub.add_client_error("admin_create_user", service_error_code="UsernameExistsException")

    with pytest.raises(create_user.AccountError, match="already taken"):
        create_user.create_person(client, POOL_ID, "alice", "Secret-password-1")


def test_any_other_failure_after_creation_also_deletes_the_user(cognito):
    client, stub = cognito
    expect_create(stub)
    stub.add_response("admin_set_user_password", {}, {**KEY, "Password": "Secret-password-1", "Permanent": True})
    stub.add_client_error("admin_add_user_to_group", service_error_code="InternalErrorException")
    stub.add_response("admin_delete_user", {}, KEY)

    with pytest.raises(Exception):
        create_user.create_person(client, POOL_ID, "alice", "Secret-password-1")


def test_the_password_must_be_typed_twice_the_same():
    answers = iter(["Secret-password-1", "Secret-password-2"])

    with pytest.raises(create_user.AccountError, match="do not match"):
        create_user.read_password(prompt=lambda _: next(answers))
