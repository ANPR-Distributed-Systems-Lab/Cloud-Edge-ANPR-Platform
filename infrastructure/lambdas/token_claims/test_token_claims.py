"""Unit tests of the pre token generation trigger: pure function, no AWS access."""

import pytest

import token_claims

ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


def trigger_event(user_attributes):
    """A minimal pre token generation event (version 2)."""
    return {
        "version": "2",
        "triggerSource": "TokenGeneration_Authentication",
        "request": {"userAttributes": user_attributes},
        "response": {},
    }


def claims_added(event, token):
    return event["response"]["claimsAndScopeOverrideDetails"][token]["claimsToAddOrOverride"]


@pytest.mark.parametrize("token", ["idTokenGeneration", "accessTokenGeneration"])
def test_copies_the_account_attribute_into_a_claim_of_both_tokens(token):
    event = trigger_event({"sub": "user-1", "custom:account_id": ACCOUNT_ID})

    result = token_claims.handler(event, None)

    assert claims_added(result, token) == {"account_id": ACCOUNT_ID}


def test_adds_no_claim_to_a_user_without_an_account():
    result = token_claims.handler(trigger_event({"sub": "user-1"}), None)

    assert claims_added(result, "idTokenGeneration") == {}
    assert claims_added(result, "accessTokenGeneration") == {}
