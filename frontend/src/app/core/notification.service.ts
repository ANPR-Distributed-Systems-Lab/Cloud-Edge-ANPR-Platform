import { Injectable, signal } from '@angular/core';

export interface Notice {
  kind: 'error' | 'success';
  text: string;
}

/** One message at a time, shown by the app shell. */
@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly current = signal<Notice | null>(null);
  readonly notice = this.current.asReadonly();

  error(text: string): void {
    this.current.set({ kind: 'error', text });
  }

  success(text: string): void {
    this.current.set({ kind: 'success', text });
  }

  clear(): void {
    this.current.set(null);
  }
}
