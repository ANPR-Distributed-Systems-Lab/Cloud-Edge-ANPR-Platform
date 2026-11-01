import { DatePipe } from "@angular/common";
import { ChangeDetectionStrategy, Component, input, output } from "@angular/core";
import { AlertResponse, AlertSortField, SortDirection } from "../../../../api/generated";

@Component({
    selector: 'app-alerts-table',
    imports: [DatePipe],
    templateUrl: './alerts-table.html',
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class AlertsTable {
    readonly alerts = input.required<AlertResponse[]>();
    readonly sort = input.required<AlertSortField>();
    readonly direction = input.required<SortDirection>();
    readonly removed = output<string>();
    readonly edited = output<AlertResponse>();
    readonly sortChanged = output<AlertSortField>();

    protected readonly SortField = AlertSortField;

    protected ariaSort(field: AlertSortField): 'ascending' | 'descending' | 'none' {
        if (this.sort() !== field) {
            return 'none';
        }
        return this.direction() === SortDirection.Asc ? 'ascending' : 'descending';
    }

    protected arrow(field: AlertSortField): string {
        if (this.sort() !== field) {
            return '';
        }
        return this.direction() === SortDirection.Asc ? '▲' : '▼';
    }
}
