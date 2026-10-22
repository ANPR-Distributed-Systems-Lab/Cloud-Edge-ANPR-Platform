import { DatePipe } from "@angular/common";
import { ChangeDetectionStrategy, Component, inject, OnInit } from "@angular/core";
import { AlertsStore } from "./alerts.store";

@Component({
    selector: 'app-alerts-page',
    imports: [DatePipe],
    templateUrl: './alerts-page.html',
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class AlertsPage implements OnInit {
    protected readonly store = inject(AlertsStore);
    private readonly fb = inject(NotnullableFormBuilder);

    ngOnInit(): void {
        this.store.load();
    }

    protected add(): void {
        if(this.form.invalid) {

        }
    }