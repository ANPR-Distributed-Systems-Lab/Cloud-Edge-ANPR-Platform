# ANPR frontend

Angular web application of the platform. Screens so far: View 4, the configuration of the device of the account
(`device-management-service`).

## Run locally

The dev server proxies `/api/v1/device` to device-management on port 8081 and the rest of `/api` to operations on port
8080 (`proxy.conf.json`), the same paths API Gateway routes in AWS. In development an interceptor adds the headers API
Gateway would inject: the account `11111111-1111-1111-1111-111111111111`, type `user`.

1. Start device-management with the `local` profile on port 8081 (both services default to 8080), e.g. in IntelliJ with
   the program argument `--server.port=8081`. It starts DynamoDB Local itself (`compose.yaml`).
2. Pair a device with the development account. Without API Gateway there is no AWS signature to check, so the request
   carries the headers the gateway injects for an administrator (`X-Account-Type: iam`); the `local` profile accepts
   any account as a person:

   ```bash
   curl -X POST http://localhost:8081/api/v1/admin/devices \
     -H "Content-Type: application/json" \
     -H "X-Account-Type: iam" -H "X-Account-Id: local-admin" \
     -d '{"accountId":"11111111-1111-1111-1111-111111111111","username":"rpi-01","password":"Local-Password-1"}'
   ```

   DynamoDB Local keeps the device across restarts; a second call returns 409 `ACCOUNT_HAS_DEVICE`.
3. `npm ci`, then `npm start` and open http://localhost:4200.

## Build and test

```bash
npm run build
npm test
```

`start`, `build` and `test` first generate the API client from `../device-management-service/device-management-api.yaml`
into `src/app/api/generated/` (not committed), so it always matches the contract.
