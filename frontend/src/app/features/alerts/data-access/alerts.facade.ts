import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AlertPage, AlertResponse, AlertSortField, CreateAlertRequest, UpdateAlertRequest } from '../../../api/generated';
import { AlertsDataService } from './alerts-data.service';
import { AlertsFilter, AlertsStore } from './alerts.store';

@Injectable({ providedIn: 'root' })
export class AlertsFacade {
  private readonly store = inject(AlertsStore);
  private readonly data = inject(AlertsDataService);

  readonly alerts = this.store.alerts;
  readonly loading = this.store.loading;
  readonly query = this.store.query;
  readonly pageMeta = this.store.pageMeta;

  load(): Observable<AlertPage> {
    return this.data.load();
  }

  changePage(page: number): Observable<AlertPage> {
    return this.data.changePage(page);
  }

  changeSort(sort: AlertSortField): Observable<AlertPage> {
    return this.data.changeSort(sort);
  }

  changeFilter(filter: AlertsFilter): Observable<AlertPage> {
    return this.data.changeFilter(filter);
  }

  get(alertId: string): Observable<AlertResponse> {
    return this.data.get(alertId);
  }

  create(request: CreateAlertRequest): Observable<AlertResponse> {
    return this.data.create(request);
  }

  update(alertId: string, request: UpdateAlertRequest): Observable<AlertResponse> {
    return this.data.update(alertId, request);
  }

  delete(alertId: string): Observable<void> {
    return this.data.delete(alertId);
  }
}