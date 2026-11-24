/** Landing buttons: 10px radius, Geist Medium (see Figma "Button v2"). */
export const buttonBase =
  "inline-flex items-center justify-center gap-1.5 rounded-[10px] font-medium tracking-[-0.01em] whitespace-nowrap transition-[background-color,box-shadow,transform] duration-200 active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lp-teal-vivid";

export const buttonTone = {
  primary: "bg-lp-ink text-white hover:bg-[#1d262c]",
  secondary:
    "border border-lp-hair bg-white text-lp-ink hover:border-[#d5d7d3] hover:bg-lp-wash",
  inverse: "bg-white text-lp-ink hover:bg-lp-wash",
  ghostDark:
    "border border-white/20 bg-white/[0.08] text-white hover:bg-white/[0.14]",
  brand: "bg-lp-teal text-white hover:bg-[#0c4d48]",
} as const;
