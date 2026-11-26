import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeCategory } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { CategoryDialog } from "./category-dialog";

let created: Record<string, unknown> | null = null;

beforeEach(() => {
  created = null;
  session.setAuthenticated("token", makeAdmin());
  server.use(
    http.post(`${API}/admin/categories`, async ({ request }) => {
      created = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(
        makeCategory({
          code: String(created.code),
          icon: String(created.icon),
        }),
        { status: 201 },
      );
    }),
  );
});

afterEach(() => session.reset());

describe("CategoryDialog icon", () => {
  // The API requires an icon on create (null is a 422), so a new category
  // starts with one and "No icon" isn't offered.
  it("creates with a default icon and offers no 'No icon' option", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <CategoryDialog
        open
        category={null}
        nextSortOrder={10}
        onOpenChange={() => {}}
      />,
    );
    const dialog = await screen.findByRole("dialog");
    const icon = within(dialog).getByLabelText("Icon");
    expect(
      within(icon).queryByRole("option", { name: "No icon" }),
    ).not.toBeInTheDocument();

    await user.type(within(dialog).getByLabelText(/^Code/), "open_manhole");
    await user.type(
      within(dialog).getByLabelText(/^Name \(English\)/),
      "Open manhole",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Create category" }),
    );

    await waitFor(() => expect(created).not.toBeNull());
    expect(created?.icon).toBe("signpost");
  });

  it("still lets an existing category clear its icon", async () => {
    renderWithProviders(
      <CategoryDialog
        open
        category={makeCategory({ icon: "construction" })}
        nextSortOrder={10}
        onOpenChange={() => {}}
      />,
    );
    const dialog = await screen.findByRole("dialog");
    const icon = within(dialog).getByLabelText("Icon");
    expect(
      within(icon).getByRole("option", { name: "No icon" }),
    ).toBeInTheDocument();
  });
});
