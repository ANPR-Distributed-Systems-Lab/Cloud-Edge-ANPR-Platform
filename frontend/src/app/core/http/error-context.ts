import { HttpContext, HttpContextToken } from '@angular/common/http';

export const SKIP_GLOBAL_ERROR = new HttpContextToken<boolean>(() => false);

export function skipGlobalError(): HttpContext {
  return new HttpContext().set(SKIP_GLOBAL_ERROR, true);
}