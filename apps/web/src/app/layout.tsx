import type { Metadata, Viewport } from "next";
import { fontVariables } from "@/lib/fonts";
import { cn } from "@/lib/utils";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "CivicPulse",
    template: "%s · CivicPulse",
  },
  description:
    "Report civic issues to your municipality and follow them until they are fixed.",
  applicationName: "CivicPulse",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf9f5" },
    { media: "(prefers-color-scheme: dark)", color: "#121b21" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={cn(fontVariables, "h-full")}>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
