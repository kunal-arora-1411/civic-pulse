import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import {
  THEME_STORAGE_KEY,
  ThemeSwitcher,
  themeScript,
} from "./theme-switcher";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("ThemeSwitcher", () => {
  it("follows the device until someone picks a theme", () => {
    renderWithProviders(<ThemeSwitcher />);
    expect(screen.getByRole("group", { name: "Theme" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Match device" })).toBeChecked();
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("applies and remembers light or dark, and can go back to the device", async () => {
    const { user } = renderWithProviders(<ThemeSwitcher />);

    await user.click(screen.getByRole("radio", { name: "Light" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("radio", { name: "Light" })).toBeChecked();

    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    await user.click(screen.getByRole("radio", { name: "Match device" }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it("restores a saved choice before first paint", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(themeScript)();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    localStorage.setItem(THEME_STORAGE_KEY, "<script>");
    document.documentElement.removeAttribute("data-theme");
    new Function(themeScript)();
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });
});
