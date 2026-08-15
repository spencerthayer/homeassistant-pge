# Auth fixtures

Sanitized PGE credential-login fixtures for `portal_auth` / CLI tests.

## Files

| File | Role |
| --- | --- |
| `login_chain.json` | Ordered Hybrid auth chain summary |
| `cognito_initiate_auth_success.json` | Cognito `USER_PASSWORD_AUTH` success shape |
| `cognito_initiate_auth_not_authorized.json` | Live-captured reject (`NotAuthorizedException`) |
| `cognito_initiate_auth_too_many_requests.json` | Live-captured throttle (`TooManyRequestsException`) |
| `cognito_password_attempts_exceeded.json` | Live-captured lockout (`NotAuthorizedException` + “Password attempts exceeded”) |
| `cognito_mfa_challenge.json` | Observed MFA challenge (`SMS_MFA`) |
| `cognito_refresh_token_auth.json` | Cognito `REFRESH_TOKEN_AUTH` renewal |
| `apigee_token_success.json` | Apigee `pg-token-implicit-aws` exchange |
| `graphql_get_account_info.json` | Account discovery GraphQL shape (`getAccountInfo` defaults) |
| `graphql_get_account_info_two_accounts_one_default.json` | Multi-account login where only the group default is returned |
| `graphql_get_account_detail_list_two_accounts.json` | `getAccountDetailList(ALL_ACCTS)` rows used to complete discovery |

## Rules

- Preserve status codes, redirect hosts/paths, cookie **names**/attributes, JSON keys.
- Replace every cookie value, token, nonce, email, person ID, and account number.
- Never commit live secrets.
- Public Cognito/Apigee **client IDs** from the portal bundle are not secrets and may appear.
