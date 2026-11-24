import { Geist, Geist_Mono, Mukta } from "next/font/google";

/*
 * Geist carries Latin text (body and headings, matching the marketing
 * site). It has no Devanagari, so the font stack falls through to Mukta for
 * Hindi, which has matching metrics for both scripts.
 *
 * Only Geist is preloaded. Preloading Mukta would push every weight of both
 * scripts to every visitor; left to unicode-range, the browser downloads
 * just the script a page actually uses, which matters on the low-bandwidth
 * connections the PRD calls out.
 */
export const latinFont = Geist({
  subsets: ["latin"],
  variable: "--font-latin",
  display: "swap",
});

export const bodyFont = Mukta({
  subsets: ["latin", "devanagari"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
  display: "swap",
  preload: false,
});

export const codeFont = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-code",
  display: "swap",
  preload: false,
});

export const fontVariables = [
  latinFont.variable,
  bodyFont.variable,
  codeFont.variable,
].join(" ");
