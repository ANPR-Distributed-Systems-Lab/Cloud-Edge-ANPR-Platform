"""Tests of the EC2 part of environment_power.py: EC2 is replaced by botocore's Stubber, so any call that a test
did not expect (for example a start in --dry-run) fails the test."""

import pytest
from botocore.stub import Stubber

import environment_power

FILTERS = [
    {"Name": "tag:finops:switch", "Values": ["true"]},
    {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
]


def instance(instance_id, state, name=None):
    tags = [{"Key": "Name", "Value": name}] if name else []
    return {"InstanceId": instance_id, "State": {"Name": state}, "Tags": tags}


def make_environment(monkeypatch, dry_run=False):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    return environment_power.Environment("anpr-dev", "anpr-dev", dry_run)


@pytest.fixture
def env(monkeypatch):
    environment = make_environment(monkeypatch)
    with Stubber(environment.ec2) as stub:
        environment.stub = stub
        yield environment
        stub.assert_no_pending_responses()


def answer_describe(env, *instances):
    env.stub.add_response(
        "describe_instances", {"Reservations": [{"Instances": list(instances)}]}, expected_params={"Filters": FILTERS}
    )


def test_lists_the_tagged_instances_by_name_and_falls_back_to_the_id(env):
    answer_describe(env, instance("i-2", "stopped"), instance("i-1", "running", name="anpr-dev-db-access"))

    assert env.instances() == [
        {"id": "i-1", "name": "anpr-dev-db-access", "state": "running"},
        {"id": "i-2", "name": "i-2", "state": "stopped"},
    ]


def test_starts_a_stopped_instance(env):
    env.stub.add_response("start_instances", {}, expected_params={"InstanceIds": ["i-1"]})

    env.start_instance({"id": "i-1", "name": "host", "state": "stopped"})


@pytest.mark.parametrize("state", ["running", "pending"])
def test_leaves_a_started_instance_alone_on_start(env, state):
    env.start_instance({"id": "i-1", "name": "host", "state": state})


def test_stops_a_running_instance(env):
    env.stub.add_response("stop_instances", {}, expected_params={"InstanceIds": ["i-1"]})

    env.stop_instance({"id": "i-1", "name": "host", "state": "running"})


@pytest.mark.parametrize("state", ["stopped", "stopping"])
def test_leaves_a_stopped_instance_alone_on_stop(env, state):
    env.stop_instance({"id": "i-1", "name": "host", "state": state})


def test_dry_run_changes_nothing(monkeypatch):
    environment = make_environment(monkeypatch, dry_run=True)
    with Stubber(environment.ec2) as stub:  # no responses added: any call would fail
        environment.start_instance({"id": "i-1", "name": "host", "state": "stopped"})
        environment.stop_instance({"id": "i-2", "name": "host", "state": "running"})
        environment.wait_for_instances("instance_running", [{"id": "i-1"}])
        stub.assert_no_pending_responses()
