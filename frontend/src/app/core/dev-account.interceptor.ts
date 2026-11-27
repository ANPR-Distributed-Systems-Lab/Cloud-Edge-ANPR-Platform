import { HttpInterceptorFn } from '@angular/common/http';

/**
 * Development only: stands in for API Gateway, which injects the identity of the caller from the
 * token in AWS. The account is a person (X-Account-Type user), so device-management acts on the
 * device of this account.
 */
const DEV_ACCOUNT_ID = '11111111-1111-1111-1111-111111111111';

export const devAccountInterceptor: HttpInterceptorFn = (req, next) =>
  next(req.clone({ setHeaders: { 'X-Account-Id': DEV_ACCOUNT_ID, 'X-Account-Type': 'user' } }));
