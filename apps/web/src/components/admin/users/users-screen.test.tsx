import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { session } from "@/lib/api";
import { makeAdmin, makeAdminUser } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { UsersScreen } from "./users-screen";

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 20,
  offset: 0,
});

const asha = makeAdminUser({
  id: "u-1",
  display_name: "Asha Rao",
  phone: "+919000000005",
});
const ravi = makeAdminUser({
  id: "u-2",
  display_name: "Ravi Kumar",
  phone: "+919000000003",
  is_staff: true,
  roles: [
    { role: "supervisor", department_id: "d-roads", jurisdiction_id: null },
  ],
});

let listRequests: URL[] = [];

beforeEach(() => {
  listRequests = [];
  session.setAuthenticated("token", makeAdmin());
  server.use(
    http.get(`${API}/admin/users`, ({ request }) => {
      const url = new URL(request.url);
      listRequests.push(url);
      const q = url.searchParams.get("q");
      return HttpResponse.json(
        page(
          q ? [ravi].filter((u) => u.display_name?.includes(q)) : [asha, ravi],
        ),
      );
    }),
    http.get(`${API}/admin/departments`, () =>
      HttpResponse.json(page([{ id: "d-roads", name: "Roads", code: "RD" }])),
    ),
    http.get(`${API}/admin/jurisdictions`, () =>
      HttpResponse.json(
        page([
          {
            id: "w-1",
            parent_id: null,
            kind: "ward",
            name: "Ward 1",
            code: "W1",
          },
        ]),
      ),
    ),
  );
});
afterEach(() => session.reset());

describe("UsersScreen", () => {
  it("lists users with their roles, scope and status", async () => {
    renderWithProviders(<UsersScreen />);

    const table = await screen.findByRole("table");
    expect(await within(table).findByText("Ravi Kumar")).toBeInTheDocument();
    expect(within(table).getByText("+91 90000 00005")).toBeInTheDocument();
    expect(await within(table).findByText(/· Roads/)).toBeInTheDocument();
    expect(within(table).getAllByText("Active")).toHaveLength(2);
  });

  it("searches by name", async () => {
    const { user } = renderWithProviders(<UsersScreen />);
    await screen.findByText("Asha Rao");

    await user.type(screen.getByLabelText("Search"), "Ravi");

    await waitFor(() => expect(screen.queryByText("Asha Rao")).toBeNull());
    expect(listRequests.at(-1)?.searchParams.get("q")).toBe("Ravi");
    expect(listRequests.at(-1)?.searchParams.get("offset")).toBe("0");
  });

  it("creates a staff user, reusing the idempotency key on retry", async () => {
    const attempts: { key: string | null; body: unknown }[] = [];
    server.use(
      http.post(`${API}/admin/users`, async ({ request }) => {
        attempts.push({
          key: request.headers.get("Idempotency-Key"),
          body: await request.json(),
        });
        if (attempts.length === 1) return HttpResponse.error();
        return HttpResponse.json(
          makeAdminUser({ id: "u-3", display_name: "Kiran Shah" }),
          { status: 201 },
        );
      }),
    );

    const { user } = renderWithProviders(<UsersScreen />);
    await screen.findByText("Asha Rao");
    await user.click(screen.getByRole("button", { name: "Add staff user" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Add a staff user",
    });
    const form = within(dialog);
    await user.type(form.getByLabelText(/full name/i), "Kiran Shah");
    await user.type(form.getByLabelText(/mobile number/i), "98765 43210");
    await user.selectOptions(form.getByLabelText(/^role 1/i), "operator");
    await user.selectOptions(form.getByLabelText(/department/i), "d-roads");

    await user.click(form.getByRole("button", { name: "Create user" }));
    expect(
      await form.findByText(/couldn't reach the server/i),
    ).toBeInTheDocument();

    // Same body again: same key, so the server can replay instead of duplicating.
    await user.click(form.getByRole("button", { name: "Create user" }));
    expect(
      await screen.findByText("Kiran Shah has been added"),
    ).toBeInTheDocument();

    expect(attempts).toHaveLength(2);
    expect(attempts[0]?.key).toBeTruthy();
    expect(attempts[1]?.key).toBe(attempts[0]?.key);
    expect(attempts[0]?.body).toEqual({
      phone: "+919876543210",
      display_name: "Kiran Shah",
      roles: [
        { role: "operator", department_id: "d-roads", jurisdiction_id: null },
      ],
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("uses a new idempotency key once the form changes", async () => {
    const keys: (string | null)[] = [];
    server.use(
      http.post(`${API}/admin/users`, ({ request }) => {
        keys.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json(
          { error: { code: "conflict", message: "Phone exists." } },
          { status: 409 },
        );
      }),
    );

    const { user } = renderWithProviders(<UsersScreen />);
    await screen.findByText("Asha Rao");
    await user.click(screen.getByRole("button", { name: "Add staff user" }));
    const form = within(await screen.findByRole("dialog"));
    await user.type(form.getByLabelText(/full name/i), "Kiran Shah");
    await user.type(form.getByLabelText(/mobile number/i), "9876543210");
    await user.selectOptions(form.getByLabelText(/^role 1/i), "operator");
    await user.click(form.getByRole("button", { name: "Create user" }));

    // A 409 is shown on the phone field itself.
    expect(
      await form.findByText("Someone already uses this mobile number."),
    ).toBeInTheDocument();
    expect(form.getByLabelText(/mobile number/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );

    await user.clear(form.getByLabelText(/mobile number/i));
    await user.type(form.getByLabelText(/mobile number/i), "9876543211");
    await user.click(form.getByRole("button", { name: "Create user" }));

    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[1]).not.toBe(keys[0]);
  });

  it("validates the form before sending anything", async () => {
    const { user } = renderWithProviders(<UsersScreen />);
    await screen.findByText("Asha Rao");
    await user.click(screen.getByRole("button", { name: "Add staff user" }));
    const form = within(await screen.findByRole("dialog"));

    await user.click(form.getByRole("button", { name: "Create user" }));

    expect(await form.findByText(/enter a name/i)).toBeInTheDocument();
    expect(form.getByText("Enter a mobile number.")).toBeInTheDocument();
    expect(form.getByText("Choose a role.")).toBeInTheDocument();
  });

  it("deactivates a user after confirmation", async () => {
    let patched: unknown;
    server.use(
      http.patch(`${API}/admin/users/u-1`, async ({ request }) => {
        patched = await request.json();
        return HttpResponse.json({ ...asha, is_active: false });
      }),
    );

    const { user } = renderWithProviders(<UsersScreen />);
    await user.click(
      await screen.findByRole("button", { name: "Deactivate Asha Rao" }),
    );
    const dialog = within(
      await screen.findByRole("dialog", { name: "Deactivate Asha Rao?" }),
    );
    await user.click(dialog.getByRole("button", { name: "Deactivate" }));

    expect(
      await screen.findByText("Asha Rao has been deactivated"),
    ).toBeInTheDocument();
    expect(patched).toEqual({ is_active: false });
  });
});
