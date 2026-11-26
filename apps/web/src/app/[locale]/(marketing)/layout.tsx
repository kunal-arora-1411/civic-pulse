import { landingFontVariables } from "@/components/landing/fonts";
import { LandingFooter } from "@/components/landing/footer";
import { LandingHeader } from "@/components/landing/header";
import { cn } from "@/lib/utils";
import "@/components/landing/landing.css";

/**
 * The public landing page has its own look (Geist, a white canvas, the
 * ribbon) and its own header and footer, separate from the citizen app.
 */
export default function MarketingLayout({
  children,
}: LayoutProps<"/[locale]">) {
  return (
    <div
      className={cn(
        landingFontVariables,
        "landing flex flex-1 flex-col bg-white font-lp text-lp-ink antialiased",
      )}
    >
      <LandingHeader />
      {children}
      <LandingFooter />
    </div>
  );
}
