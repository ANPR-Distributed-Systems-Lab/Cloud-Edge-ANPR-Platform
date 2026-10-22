import { HttpInterceptorFn } from '@angular/common/http';

const DEV_ACCOUNT_ID = '11111111-1111-1111-1111-111111111111';

export const devAccountInterceptor: HttpInterceptorFn = (req, next) => {
  return next(req.clone({ setHeaders: { 'X-Account-Id': DEV_ACCOUNT_ID } }));
};