import type { I18nText } from "@/lib/api";

/**
 * Pick the user's language from an `_i18n` object, falling back to
 * English and then to whatever language is present (contract: "the client
 * picks the user's locale and falls back to en").
 */
export function localized(
  text: I18nText | null | undefined,
  locale: string,
): string {
  if (!text) return "";
  return text[locale] || text.en || Object.values(text).find(Boolean) || "";
}
