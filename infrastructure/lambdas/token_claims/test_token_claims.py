"""Unit tests of the pre token generation trigger: pure function, no AWS access."""

import importlib
import json

import pytest

ACCOUNT_TYPE_BY_GROUP = {"users": "user", "devices": "device"}


@pytest.fixture
def token_claims(monkeypatch):
    """The trigger module, imported with the environment Terraform gives the function."""
    monkeypatch.setenv("ACCOUNT_TYPE_BY_GROUP", json.dumps(ACCOUNT_TYPE_BY_GROUP))
    import token_claims

    return importlib.reload(token_claims)  # re-read the environment for every test


def trigger_event(groups=None):
    """A minimal pre token generation event (version 2) of a user who is in the given groups."""
    request = {"userAttributes": {"sub": "user-1"}}
    if groups is not None:
        request["groupConfiguration"] = {"groupsToOverride": groups, "iamRolesToOverride": []}
    return {"version": "2", "triggerSource": "TokenGeneration_Authentication", "request": request, "response": {}}


def claims_added(event, token):
    return event["response"]["claimsAndScopeOverrideDetails"][token]["claimsToAddOrOverride"]


@pytest.mark.parametrize("token", ["idTokenGeneration", "accessTokenGeneration"])
@pytest.mark.parametrize(
    "group, account_type",
    [("users", "user"), ("devices", "device")],
)
def test_turns_the_group_into_the_account_type_claim_of_both_tokens(token_claims, token, group, account_type):
    result = token_claims.handler(trigger_event([group]), None)

    assert claims_added(result, token) == {"account_type": account_type}


def test_ignores_groups_that_are_not_account_groups(token_claims):
    result = token_claims.handler(trigger_event(["beta-testers", "devices"]), None)

    assert claims_added(result, "accessTokenGeneration") == {"account_type": "device"}


@pytest.mark.parametrize("groups", [None, [], ["beta-testers"]])
def test_adds_no_claim_to_a_user_without_an_account_group(token_claims, groups):
    result = token_claims.handler(trigger_event(groups), None)

    assert claims_added(result, "idTokenGeneration") == {}
    assert claims_added(result, "accessTokenGeneration") == {}


def test_adds_no_claim_when_the_groups_disagree_on_the_account_type(token_claims):
    result = token_claims.handler(trigger_event(["users", "devices"]), None)

    assert claims_added(result, "idTokenGeneration") == {}
    assert claims_added(result, "accessTokenGeneration") == {}
