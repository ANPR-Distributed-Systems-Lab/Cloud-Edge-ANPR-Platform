import { Injectable, inject } from '@angular/core';
import { Observable, concatMap, defer, finalize, map, of, tap } from 'rxjs';
import {
  AlertPage,
  AlertResponse,
  AlertSortField,
  AlertsService,
  CreateAlertRequest,
  SortDirection,
  UpdateAlertRequest,
} from '../../../api/generated';
import { skipGlobalError } from '../../../core/http/error-context';
import { AlertsFilter, AlertsQuery, AlertsStore } from './alerts.store';

@Injectable({ providedIn: 'root' })
export class AlertsDataService {
  private readonly api = inject(AlertsService);
  private readonly store = inject(AlertsStore);

  load(): Observable<AlertPage> {
    return defer(() => {
      const { page, size, sort, direction, plate, from, to } = this.store.query();
      this.store.setLoading(true);
      return this.api
        .listAlerts(
          page,
          size,
          sort,
          direction,
          orUndefined(plate),
          orUndefined(from),
          orUndefined(to),
        )
        .pipe(
          tap((result) => {
            this.store.setAlerts(result.items);
            this.store.setPageMeta(result.page);
          }),
          finalize(() => this.store.setLoading(false)),
        );
    });
  }

  changePage(page: number): Observable<AlertPage> {
    return this.reloadWith(() => ({ page }));
  }

  changeSort(sort: AlertSortField): Observable<AlertPage> {
    return this.reloadWith((current) => ({
      sort,
      direction:
        current.sort === sort && current.direction === SortDirection.Desc
          ? SortDirection.Asc
          : SortDirection.Desc,
      page: 0,
    }));
  }

  changeFilter(filter: AlertsFilter): Observable<AlertPage> {
    return this.reloadWith(() => ({ ...filter, page: 0 }));
  }

  get(alertId: string): Observable<AlertResponse> {
    return this.api.getAlert(alertId);
  }

  create(request: CreateAlertRequest): Observable<AlertResponse> {
    return this.api
      .createAlert(request)
      .pipe(concatMap((created) => this.load().pipe(map(() => created))));
  }

  update(alertId: string, request: UpdateAlertRequest): Observable<AlertResponse> {
    return this.api
      .updateAlert(alertId, request, 'body', false, { context: skipGlobalError() })
      .pipe(concatMap((updated) => this.load().pipe(map(() => updated))));
  }

  delete(alertId: string): Observable<void> {
    return this.api.deleteAlert(alertId).pipe(
      concatMap(() => this.load()),
      concatMap((result) =>
        result.items.length === 0 && result.page.page > 0
          ? this.changePage(result.page.page - 1)
          : of(result),
      ),
      map(() => undefined),
    );
  }

  /** Changes the query on subscribe (not on call, see `load`) and reloads the list with it. */
  private reloadWith(
    change: (current: AlertsQuery) => Partial<AlertsQuery>,
  ): Observable<AlertPage> {
    return defer(() => {
      const current = this.store.query();
      this.store.setQuery({ ...current, ...change(current) });
      return this.load();
    });
  }
}

function orUndefined(value: string): string | undefined {
  return value === '' ? undefined : value;
}
