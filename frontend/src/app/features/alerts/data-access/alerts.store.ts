import { Injectable, signal } from "@angular/core";
import { AlertResponse, AlertSortField, PageMeta, SortDirection } from '../../../api/generated';

export interface AlertsFilter {
    plate: string;
    from: string;
    to: string;
}

export interface AlertsQuery extends AlertsFilter {
    page: number;
    size: number;
    sort: AlertSortField;
    direction: SortDirection;
}

const DEFAULT_QUERY: AlertsQuery = {
    page: 0,
    size: 20,
    sort: AlertSortField.CreatedAt,
    direction: SortDirection.Desc,
    plate: '',
    from: '',
    to: ''
};

@Injectable({ providedIn: 'root' })
export class AlertsStore {
    private readonly alertsState = signal<AlertResponse[]>([]);
    private readonly loadingState = signal<boolean>(false);
    private readonly queryState = signal<AlertsQuery>(DEFAULT_QUERY);
    private readonly pageMetaState = signal<PageMeta | null>(null);

    readonly alerts = this.alertsState.asReadonly();
    readonly loading = this.loadingState.asReadonly();
    readonly query = this.queryState.asReadonly();
    readonly pageMeta = this.pageMetaState.asReadonly();

    setAlerts(alerts: AlertResponse[]): void {
        this.alertsState.set(alerts);
    }

    setLoading(loading: boolean): void {
        this.loadingState.set(loading);
    }

    setQuery(query: AlertsQuery): void {
        this.queryState.set(query);
    }

    setPageMeta(pageMeta: PageMeta): void {
        this.pageMetaState.set(pageMeta);
    }
}
