/**
 * Indian mobile numbers are 10 digits starting with 6–9. People type them
 * in many shapes: with a leading 0 (trunk prefix), with 91 or +91, and with
 * spaces or dashes from copy-pasting. We accept all of those and send the
 * API E.164 (`+919876543210`), matching what the backend stores.
 */
const MOBILE = /^[6-9]\d{9}$/;

export function normalizeIndianPhone(input: string): string | null {
  const trimmed = input.trim();
  const hasPlus = trimmed.startsWith("+");
  const digits = trimmed.replace(/[\s\-().]/g, "").replace(/^\+/, "");
  if (!/^\d+$/.test(digits)) return null;

  let national: string;
  if (hasPlus) {
    // With an explicit +, only the Indian country code is accepted.
    if (!digits.startsWith("91")) return null;
    national = digits.slice(2);
  } else if (digits.length === 12 && digits.startsWith("91")) {
    national = digits.slice(2);
  } else if (digits.length === 11 && digits.startsWith("0")) {
    national = digits.slice(1);
  } else {
    national = digits;
  }

  return MOBILE.test(national) ? `+91${national}` : null;
}

/** `+919876543210` → `+91 98765 43210`. Leaves other formats untouched. */
export function formatIndianPhone(e164: string): string {
  const match = /^\+91(\d{5})(\d{5})$/.exec(e164);
  return match ? `+91 ${match[1]} ${match[2]}` : e164;
}

/** `+919876543210` → `+91 ••••• •3210`, for confirmations on shared screens. */
export function maskIndianPhone(e164: string): string {
  const match = /^\+91\d{6}(\d{4})$/.exec(e164);
  return match ? `+91 ••••• •${match[1]}` : e164;
}
