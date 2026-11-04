"""Pre token generation trigger of the Cognito user pool (event version V2_0).

The kind of account, a person or an edge device, is the group its user belongs to in the pool. API Gateway
can pass a token claim to a service as a header only when the claim name contains letters, digits, "." and
"_"; the group claim is called cognito:groups and is a list. So this trigger turns the group into a plain
claim named account_type ("user" or "device"), in both the ID token and the access token.

ACCOUNT_TYPE_BY_GROUP (set by Terraform, see auth.tf) maps a group name to its account type. A user who is in
no known group, or in groups of different types, gets tokens without the claim; the backends refuse such a
caller.
"""

import json
import os

ACCOUNT_TYPE_BY_GROUP = json.loads(os.environ["ACCOUNT_TYPE_BY_GROUP"])
ACCOUNT_TYPE_CLAIM = "account_type"


def handler(event, context):
    groups = event["request"].get("groupConfiguration", {}).get("groupsToOverride") or []
    account_types = {ACCOUNT_TYPE_BY_GROUP[group] for group in groups if group in ACCOUNT_TYPE_BY_GROUP}
    claims = {ACCOUNT_TYPE_CLAIM: account_types.pop()} if len(account_types) == 1 else {}

    event["response"] = {
        "claimsAndScopeOverrideDetails": {
            "idTokenGeneration": {"claimsToAddOrOverride": claims},
            "accessTokenGeneration": {"claimsToAddOrOverride": claims},
        }
    }
    return event
