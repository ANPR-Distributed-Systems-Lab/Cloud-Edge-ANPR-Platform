"""Pre token generation trigger of the Cognito user pool (event version V2_0).

API Gateway can pass a token claim to a service as a header only when the claim name contains
letters, digits, "." and "_". The account of a user is stored in the attribute custom:account_id,
whose name has a colon, so this trigger copies it into a claim named account_id, in both the ID
token and the access token.

A user without an account gets tokens without the claim; the API rejects such requests downstream.
"""

ACCOUNT_ATTRIBUTE = "custom:account_id"
ACCOUNT_CLAIM = "account_id"


def handler(event, context):
    account_id = event["request"]["userAttributes"].get(ACCOUNT_ATTRIBUTE)
    claims = {ACCOUNT_CLAIM: account_id} if account_id else {}

    event["response"] = {
        "claimsAndScopeOverrideDetails": {
            "idTokenGeneration": {"claimsToAddOrOverride": claims},
            "accessTokenGeneration": {"claimsToAddOrOverride": claims},
        }
    }
    return event
