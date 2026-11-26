import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

/*
 * Automated accessibility checks (P6-04, WCAG 2.2 AA), shared by the specs
 * that already hold a session for the page under test.
 */

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Fail on serious or critical axe violations; attach the rest. */
export async function expectAccessible(page: Page, name: string) {
  // Measure the settled page: an entrance fade-in caught half way reads as
  // low contrast. Endless animations (skeletons, spinners) are ignored.
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .every(
        (animation) =>
          animation.playState !== "running" ||
          animation.effect?.getComputedTiming().iterations === Infinity,
      ),
  );
  // Leaflet's tiles and controls are third-party markup we can't change.
  const results = await new AxeBuilder({ page })
    .withTags(TAGS)
    .exclude(".leaflet-container")
    .analyze();
  await test.info().attach(`axe-${name}.json`, {
    body: JSON.stringify(results.violations, null, 2),
    contentType: "application/json",
  });
  const blocking = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({
      rule: v.id,
      impact: v.impact,
      help: v.help,
      targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
    }));
  expect(blocking, `${name}: serious or critical axe violations`).toEqual([]);
}
