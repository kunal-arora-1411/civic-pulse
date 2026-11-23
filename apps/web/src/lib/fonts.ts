import { Bricolage_Grotesque, JetBrains_Mono, Mukta } from "next/font/google";

/*
 * Mukta covers both Latin and Devanagari with matching metrics, so Hindi and
 * English text sit comfortably side by side. Bricolage Grotesque gives
 * headings some character; Devanagari headings fall back to Mukta.
 *
 * Only the heading face is preloaded. Preloading Mukta would push every
 * weight of both scripts to every visitor; left to unicode-range, the
 * browser downloads just the script a page actually uses, which matters on
 * the low-bandwidth connections the PRD calls out.
 */
export const bodyFont = Mukta({
  subsets: ["latin", "devanagari"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
  display: "swap",
  preload: false,
});

export const displayFont = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-display-face",
  display: "swap",
});

export const codeFont = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-code",
  display: "swap",
  preload: false,
});

export const fontVariables = [
  bodyFont.variable,
  displayFont.variable,
  codeFont.variable,
].join(" ");
