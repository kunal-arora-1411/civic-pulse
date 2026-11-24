import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import { makeSignals } from "@/test/signals";
import { SignalBreakdown } from "./signal-breakdown";

function signalItem(name: string) {
  const list = screen.getByRole("list", { name: "Signals" });
  const item = within(list)
    .getAllByRole("listitem")
    .find((li) => li.textContent?.startsWith(name));
  if (!item) throw new Error(`No signal named ${name}`);
  return item;
}

describe("SignalBreakdown", () => {
  it("writes out each signal's evidence, strength, weight and contribution", () => {
    renderWithProviders(
      <SignalBreakdown signals={makeSignals()} score={0.78} />,
    );

    const distance = signalItem("Distance");
    expect(distance).toHaveTextContent("18 m apart. Matching radius 30 m.");
    expect(distance).toHaveTextContent("Strength 0.54");
    expect(distance).toHaveTextContent("Within the radius");
    expect(distance).toHaveTextContent("Weight 0.40 · adds 0.22");

    const visual = signalItem("Photo similarity");
    expect(visual).toHaveTextContent("Strength 0.91");
    expect(visual).toHaveTextContent(
      "Linking automatically needs at least 0.80.",
    );
    expect(visual).toHaveTextContent("Meets the auto-link minimum");

    expect(signalItem("Category")).toHaveTextContent("Same category.");
    expect(signalItem("Recency")).toHaveTextContent(
      "2.1 days since the issue's last report.",
    );
  });

  it("states the score against both thresholds in words", () => {
    renderWithProviders(
      <SignalBreakdown signals={makeSignals()} score={0.78} />,
    );
    const score = screen.getByRole("region", { name: "Match score" });
    expect(score).toHaveTextContent("0.78");
    expect(score).toHaveTextContent(
      "Between the review threshold (0.60) and the auto-link threshold (0.85), so a person decides.",
    );
  });

  it("says why a high score still went to a person", () => {
    renderWithProviders(
      <SignalBreakdown
        signals={makeSignals({ distance_m: 42, geo: 0.25 })}
        score={0.87}
      />,
    );
    expect(
      screen.getByText(
        "High enough to link automatically, but it's outside the matching radius, so a person decides.",
      ),
    ).toBeInTheDocument();
    expect(signalItem("Distance")).toHaveTextContent("Outside the radius");
  });

  it("explains a missing photo comparison and flags a re-used photo", () => {
    const { unmount } = renderWithProviders(
      <SignalBreakdown
        signals={makeSignals({ visual: null, reason: "ai_unavailable" })}
        score={0.62}
      />,
    );
    const visual = signalItem("Photo similarity");
    expect(visual).toHaveTextContent("Not available");
    expect(visual).toHaveTextContent(/couldn't be compared/);
    // The weight moved to the other signals: 0.4 / 0.6.
    expect(signalItem("Distance")).toHaveTextContent("Weight 0.67");
    unmount();

    renderWithProviders(
      <SignalBreakdown
        signals={makeSignals({ visual: 1, same_photo: true })}
        score={0.95}
      />,
    );
    expect(signalItem("Photo similarity")).toHaveTextContent(
      "Looks like the same photo",
    );
    expect(
      screen.getByText("Strong enough to be linked automatically."),
    ).toBeInTheDocument();
  });

  it("keeps the bars out of the accessibility tree", () => {
    const { container } = renderWithProviders(
      <SignalBreakdown signals={makeSignals()} score={0.78} />,
    );
    for (const bar of container.querySelectorAll("[style*='width']")) {
      expect(bar.closest("[aria-hidden='true']")).not.toBeNull();
    }
  });
});
