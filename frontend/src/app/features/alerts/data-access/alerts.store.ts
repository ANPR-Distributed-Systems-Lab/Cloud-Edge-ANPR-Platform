import { inject, Injectable, signal } from "@angular/core";
import { AlertResponse, AlertsService } from '../../../api/generated';
import { finalize } from "rxjs";


@Injectable({ providedIn: 'root' })
export class AlertsStore {
    private readonly alertsState = signal<AlertResponse[]>([]);
    private readonly loadingState = signal<boolean>(false);

    readonly alerts = this.alertsState.asReadonly();
    readonly loading = this.loadingState.asReadonly();

    setAlerts(alerts: AlertResponse[]): void {
        this.alertsState.set(alerts);
    }

    setLoading(loading: boolean): void {
        this.loadingState.set(loading);
    }
}