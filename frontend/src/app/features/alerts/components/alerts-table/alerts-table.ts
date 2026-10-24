import { DatePipe } from "@angular/common";
import { ChangeDetectionStrategy, Component, input, output } from "@angular/core";
import { AlertResponse } from "../../../../api/generated";

@Component({
    selector: 'app-alerts-table',
    imports: [DatePipe],
    templateUrl: './alerts-table.html',
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class AlertsTable {
    readonly alerts = input.required<AlertResponse[]>();
    readonly removed = output<string>();
}