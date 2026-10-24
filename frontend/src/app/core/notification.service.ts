import { Injectable, signal } from "@angular/core";

@Injectable({ providedIn: 'root' })
export class NotificationService {
    readonly message = signal<string | null>(null);

    error(text: string): void {
        this.message.set(text);
    }

    clear(): void {
        this.message.set(null);
    }
}