import { Bricolage_Grotesque, JetBrains_Mono, Mukta } from "next/font/google";

/*
 * Mukta covers both Latin and Devanagari with matching metrics, so Hindi and
 * English text sit comfortably side by side. Bricolage Grotesque gives
 * headings some character; Devanagari headings fall back to Mukta.
 */
export const bodyFont = Mukta({
  subsets: ["latin", "devanagari"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
  display: "swap",
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
});

export const fontVariables = [
  bodyFont.variable,
  displayFont.variable,
  codeFont.variable,
].join(" ");
