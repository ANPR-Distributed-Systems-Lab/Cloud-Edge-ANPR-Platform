import { inject, Injectable, signal } from "@angular/core";
import { AlertResponse, AlertsService } from '../../api/generated';
import { finalize } from "rxjs";


@Injectable({ providedIn: 'root' })
export class AlertsStore {
    private readonly api = inject(AlertsService);

    readonly alerts = signal<AlertResponse[]>([]);
    readonly loading = signal(false);

    load(): void {
        this.loading.set(true);
        this.api.listAlerts(0, 20)
            .pipe(finalize(() => this.loading.set(false)))
            .subscribe(page => this.alerts.set(page.items));
    }

    create(plate: string, alertText?: string): void {
        this.api.createAlert({ plate, alertText }).subscribe(() => this.load());
    }

    delete(alertId: string): void {
        this.api.deleteAlert(alertId).subscribe(() => this.load());
    }
    

}