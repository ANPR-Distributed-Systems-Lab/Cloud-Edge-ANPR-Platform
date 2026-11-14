"""Tests of environment_reset.py: every AWS client is replaced by botocore's Stubber, so a call that a test did not
expect (for example a delete in dry-run) fails the test."""

import pytest
from botocore.stub import Stubber

import environment_reset
from environment_reset import Reset

CLIENTS = ("sqs", "dynamodb", "s3", "cognito", "ssm", "sts")
TABLE = "anpr-dev-devices"
KEY_SCHEMA = {"Table": {"KeySchema": [{"AttributeName": "deviceId", "KeyType": "HASH"}]}}


def make_reset(monkeypatch, dry_run=False):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    return Reset("anpr-dev", dry_run)


@pytest.fixture
def reset(monkeypatch):
    instance = make_reset(monkeypatch)
    stubs = {name: Stubber(getattr(instance, name)) for name in CLIENTS}
    for stub in stubs.values():
        stub.activate()
    instance.stubs = stubs
    yield instance
    for stub in stubs.values():
        stub.assert_no_pending_responses()


def keys(*ids):
    return [{"deviceId": {"S": i}} for i in ids]


def expect_table_scan(reset, items):
    stub = reset.stubs["dynamodb"]
    stub.add_response("list_tables", {"TableNames": [TABLE, "other-table"]})
    stub.add_response("describe_table", KEY_SCHEMA, expected_params={"TableName": TABLE})
    stub.add_response(
        "scan",
        {"Items": items},
        expected_params={
            "TableName": TABLE,
            "ProjectionExpression": "#k0",
            "ExpressionAttributeNames": {"#k0": "deviceId"},
        },
    )


def test_reads_host_port_and_database_from_the_jdbc_url():
    url = "jdbc:postgresql://anpr-dev-operations.abc.eu-central-1.rds.amazonaws.com:5432/operations?sslmode=require"

    assert environment_reset.parse_jdbc_url(url) == (
        "anpr-dev-operations.abc.eu-central-1.rds.amazonaws.com",
        "5432",
        "operations",
    )


def test_the_schema_script_reads_the_password_on_the_host_and_stops_at_the_first_error():
    script = environment_reset.reset_schema_script(
        "db.internal", "5432", "operations", "admin", "eu-central-1", "/anpr/dev/operations-service/datasource-password"
    )

    text = "\n".join(script)
    assert "--name /anpr/dev/operations-service/datasource-password" in text
    assert "ON_ERROR_STOP=1" in text and "set -euo pipefail" in text
    assert "DROP SCHEMA public CASCADE" in text and "CREATE SCHEMA public" in text
    assert "host=db.internal port=5432 dbname=operations user=admin sslmode=require" in text


def test_deletes_every_item_of_the_environment_tables_in_batches_of_25(reset):
    expect_table_scan(reset, keys(*[f"d{i}" for i in range(26)]))
    stub = reset.stubs["dynamodb"]
    for count in (25, 1):
        stub.add_response("batch_write_item", {"UnprocessedItems": {}})

    reset.clear_tables()  # the stubbed calls were all consumed: the other table was left alone


def test_retries_the_items_dynamodb_returns_unprocessed(reset):
    expect_table_scan(reset, keys("d1"))
    stub = reset.stubs["dynamodb"]
    unprocessed = [{"DeleteRequest": {"Key": {"deviceId": {"S": "d1"}}}}]
    stub.add_response("batch_write_item", {"UnprocessedItems": {TABLE: unprocessed}})
    stub.add_response("batch_write_item", {"UnprocessedItems": {}}, expected_params={"RequestItems": {TABLE: unprocessed}})

    reset.clear_tables()


def test_dry_run_only_counts_the_items(monkeypatch):
    reset = make_reset(monkeypatch, dry_run=True)
    with Stubber(reset.dynamodb) as stub:
        stub.add_response("list_tables", {"TableNames": [TABLE]})
        stub.add_response("describe_table", KEY_SCHEMA)
        stub.add_response("scan", {"Items": keys("d1", "d2")})  # no batch_write_item answer: a delete would fail

        reset.clear_tables()

        stub.assert_no_pending_responses()


def test_deletes_every_user_of_the_pool_with_the_environment_name(reset):
    stub = reset.stubs["cognito"]
    stub.add_response("list_user_pools", {"UserPools": [{"Id": "pool-other", "Name": "other"}, {"Id": "pool-1", "Name": "anpr-dev"}]})
    stub.add_response("list_users", {"Users": [{"Username": "device-1"}, {"Username": "kamil"}]}, expected_params={"UserPoolId": "pool-1"})
    for name in ("device-1", "kamil"):
        stub.add_response("admin_delete_user", {}, expected_params={"UserPoolId": "pool-1", "Username": name})

    reset.delete_users()


def test_refuses_to_delete_users_when_the_pool_is_not_unique(reset):
    reset.stubs["cognito"].add_response("list_user_pools", {"UserPools": []})

    with pytest.raises(SystemExit):
        reset.delete_users()


def test_purges_every_queue_of_the_environment(reset):
    url = "https://sqs.eu-central-1.amazonaws.com/123456789012/anpr-dev-operations-events"
    stub = reset.stubs["sqs"]
    stub.add_response("list_queues", {"QueueUrls": [url]}, expected_params={"QueueNamePrefix": "anpr-dev-"})
    stub.add_response("get_queue_attributes", {"Attributes": {"ApproximateNumberOfMessages": "7"}})
    stub.add_response("purge_queue", {}, expected_params={"QueueUrl": url})

    reset.purge_queues()


def test_empties_only_the_storage_bucket(reset):
    reset.stubs["sts"].add_response("get_caller_identity", {"Account": "123456789012", "UserId": "u", "Arn": "arn:aws:iam::123456789012:user/test"})
    stub = reset.stubs["s3"]
    bucket = "anpr-dev-storage-123456789012"
    stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "images/a.jpg"}, {"Key": "images/b.jpg"}]},
        expected_params={"Bucket": bucket},
    )
    stub.add_response(
        "delete_objects",
        {},
        expected_params={
            "Bucket": bucket,
            "Delete": {"Objects": [{"Key": "images/a.jpg"}, {"Key": "images/b.jpg"}], "Quiet": True},
        },
    )

    reset.empty_bucket()


def test_nothing_is_deleted_without_the_confirmation(monkeypatch):
    created = []
    monkeypatch.setattr(environment_reset, "Reset", lambda prefix, dry_run: created.append(dry_run) or type("R", (), {"run": lambda self: None})())

    monkeypatch.setattr("sys.argv", ["environment_reset.py", "--prefix", "anpr-dev"])
    environment_reset.main()
    monkeypatch.setattr("sys.argv", ["environment_reset.py", "--prefix", "anpr-dev", "--confirm", "anpr-dev"])
    environment_reset.main()

    assert created == [True, False]


def test_a_wrong_confirmation_is_refused(monkeypatch):
    monkeypatch.setattr("sys.argv", ["environment_reset.py", "--prefix", "anpr-dev", "--confirm", "anpr-prod"])

    with pytest.raises(SystemExit):
        environment_reset.main()
