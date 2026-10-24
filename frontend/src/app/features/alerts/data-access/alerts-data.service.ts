import { Injectable, inject } from '@angular/core';
import { Observable, finalize, switchMap, tap } from 'rxjs';
import { AlertPage, AlertsService, CreateAlertRequest } from '../../../api/generated';
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

  create(request: CreateAlertRequest): Observable<AlertPage> {
    return this.api.createAlert(request).pipe(switchMap(() => this.load()));
  }

  delete(alertId: string): Observable<AlertPage> {
    return this.api.deleteAlert(alertId).pipe(switchMap(() => this.load()));
  }
}