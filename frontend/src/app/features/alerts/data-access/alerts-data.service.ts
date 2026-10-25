import { Injectable, inject } from '@angular/core';
import { Observable, concatMap, finalize, map, tap } from 'rxjs';
import {
  AlertPage,
  AlertResponse,
  AlertsService,
  CreateAlertRequest,
  UpdateAlertRequest
} from '../../../api/generated';
import { skipGlobalError } from '../../../core/http/error-context';
import { AlertsStore } from './alerts.store';

@Injectable({ providedIn: 'root' })
export class AlertsDataService {
  private readonly api = inject(AlertsService);
  private readonly store = inject(AlertsStore);

  load(): Observable<AlertPage> {
    this.store.setLoading(true);
    return this.api.listAlerts(0, 20).pipe(
      tap(page => this.store.setAlerts(page.items)),
      finalize(() => this.store.setLoading(false))
    );
  }

  get(alertId: string): Observable<AlertResponse> {
    return this.api.getAlert(alertId);
  }

  create(request: CreateAlertRequest): Observable<AlertResponse> {
    return this.api.createAlert(request).pipe(
      concatMap(created => this.load().pipe(map(() => created)))
    );
  }

  update(alertId: string, request: UpdateAlertRequest): Observable<AlertResponse> {
    return this.api
      .updateAlert(alertId, request, 'body', false, { context: skipGlobalError() })
      .pipe(
        concatMap(updated => this.load().pipe(map(() => updated)))
      );
  }

  delete(alertId: string): Observable<void> {
    return this.api.deleteAlert(alertId).pipe(
      concatMap(() => this.load()),
      map(() => undefined)
    );
  }
}