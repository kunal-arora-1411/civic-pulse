import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import { LanguageSwitcher } from "./language-switcher";

const switchLocale = vi.hoisted(() => vi.fn());
vi.mock("@/i18n/switch-locale", () => ({ switchLocale }));

describe("LanguageSwitcher", () => {
  it("shows both languages as a radio group with the current one checked", () => {
    renderWithProviders(<LanguageSwitcher />);
    const group = screen.getByRole("group", { name: "Language" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "English" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "हिन्दी" })).not.toBeChecked();
  });

  it("switches language, and does nothing for the current one", async () => {
    const { user } = renderWithProviders(<LanguageSwitcher />);

    await user.click(screen.getByRole("radio", { name: "हिन्दी" }));
    expect(switchLocale).toHaveBeenLastCalledWith("hi");

    switchLocale.mockClear();
    await user.click(screen.getByRole("radio", { name: "English" }));
    expect(switchLocale).not.toHaveBeenCalled();
  });
});
