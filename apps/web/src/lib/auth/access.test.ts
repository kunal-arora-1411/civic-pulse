import { describe, expect, it } from "vitest";
import type { RoleAssignment } from "@/lib/api";
import { makeUser } from "@/test/fixtures";
import {
  canUseAdmin,
  canUseField,
  hasPermission,
  homePathFor,
  safeNextPath,
} from "./access";

const role = (name: RoleAssignment["role"]): RoleAssignment => ({
  role: name,
  department_id: null,
  jurisdiction_id: null,
});

describe("homePathFor", () => {
  it("sends citizens home", () => {
    expect(homePathFor(makeUser())).toBe("/");
  });

  it.each([
    "operator",
    "supervisor",
    "municipal_admin",
    "platform_admin",
  ] as const)("sends %s to the admin console", (name) => {
    expect(homePathFor(makeUser({ is_staff: true, roles: [role(name)] }))).toBe(
      "/admin",
    );
  });

  it("sends field-worker-only staff to the field app", () => {
    const worker = makeUser({ is_staff: true, roles: [role("field_worker")] });
    expect(homePathFor(worker)).toBe("/field");
    expect(canUseAdmin(worker)).toBe(false);
    expect(canUseField(worker)).toBe(true);
  });

  it("prefers the console for a field worker who also supervises", () => {
    const user = makeUser({
      is_staff: true,
      roles: [role("field_worker"), role("supervisor")],
    });
    expect(homePathFor(user)).toBe("/admin");
  });

  it("treats a community contributor as a citizen", () => {
    expect(
      homePathFor(makeUser({ roles: [role("community_contributor")] })),
    ).toBe("/");
  });
});

describe("hasPermission", () => {
  it("checks the permission list", () => {
    const user = makeUser({ permissions: ["audit:read"] });
    expect(hasPermission(user, "audit:read")).toBe(true);
    expect(hasPermission(user, "user:manage")).toBe(false);
    expect(hasPermission(null, "audit:read")).toBe(false);
  });
});

describe("safeNextPath", () => {
  it.each([
    ["/admin/users", "/admin/users"],
    ["/admin/audit?action=user.created", "/admin/audit?action=user.created"],
  ])("accepts %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([
    [null],
    [""],
    ["https://evil.example"],
    ["//evil.example"],
    ["/\\evil.example"],
    ["admin"],
    ["/login"],
  ])("rejects %j", (input) => {
    expect(safeNextPath(input)).toBeNull();
  });
});
