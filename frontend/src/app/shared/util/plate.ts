/** Keeps only uppercase letters and digits, the form the API accepts (`wa 12-345` → `WA12345`). */
export function normalizePlate(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, '');
}
