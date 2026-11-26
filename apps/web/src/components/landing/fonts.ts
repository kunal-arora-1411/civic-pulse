import { Anek_Devanagari, Geist, Geist_Mono } from "next/font/google";

/*
 * The landing page has its own type: Geist for text and headings, Geist
 * Mono for figures, and Anek Devanagari for Hindi. They load only on the
 * landing page; the app's other screens keep Mukta and Bricolage.
 *
 * Geist has no Devanagari glyphs, so Hindi falls through to Anek in the
 * font stack. Anek isn't preloaded: its unicode-range means English
 * visitors never download it.
 */
const geist = Geist({
  subsets: ["latin"],
  variable: "--font-geist",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
  preload: false,
});

const anek = Anek_Devanagari({
  subsets: ["devanagari"],
  weight: ["400", "500", "600"],
  variable: "--font-anek",
  display: "swap",
  preload: false,
});

export const landingFontVariables = [
  geist.variable,
  geistMono.variable,
  anek.variable,
].join(" ");
