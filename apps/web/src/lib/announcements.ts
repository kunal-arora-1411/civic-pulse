/*
 * Service announcements are scheduled in the city's time, India Standard
 * Time, whatever zone the administrator's browser is in. A
 * <input type="datetime-local"> value ("2026-11-26T18:00") is read as IST.
 */

const IST_OFFSET = "+05:30";
const IST_OFFSET_MS = 330 * 60_000;
const LOCAL_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** "2026-11-26T18:00" (IST) -> an ISO instant, or null when incomplete. */
export function istInputToIso(value: string): string | null {
  if (!LOCAL_RE.test(value)) return null;
  const date = new Date(`${value}:00${IST_OFFSET}`);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** An instant -> the datetime-local value showing it in IST. */
export function isoToIstInput(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() + IST_OFFSET_MS).toISOString().slice(0, 16);
}

/** Now plus `hours`, as an IST datetime-local value (form defaults). */
export function istInputFromNow(hours = 0, now: Date = new Date()): string {
  return isoToIstInput(
    new Date(now.getTime() + hours * 3_600_000).toISOString(),
  );
}
