import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AlertPage, CreateAlertRequest } from '../../../api/generated';
import { AlertsDataService } from './alerts-data.service';
import { AlertsStore } from './alerts.store';

@Injectable({ providedIn: 'root' })
export class AlertsFacade {
  private readonly store = inject(AlertsStore);
  private readonly data = inject(AlertsDataService);

  readonly alerts = this.store.alerts;
  readonly loading = this.store.loading;

  load(): Observable<AlertPage> {
    return this.data.load();
  }

  create(request: CreateAlertRequest): Observable<AlertPage> {
    return this.data.create(request);
  }

  delete(alertId: string): Observable<AlertPage> {
    return this.data.delete(alertId);
  }
}