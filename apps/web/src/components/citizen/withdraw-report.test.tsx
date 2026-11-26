import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { makeReport } from "@/test/fixtures";
import { API, server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { WithdrawReport } from "./withdraw-report";

describe("WithdrawReport", () => {
  it("withdraws after confirming", async () => {
    let called = false;
    server.use(
      http.post(`${API}/reports/rep-1/withdraw`, () => {
        called = true;
        return HttpResponse.json(makeReport({ status: "withdrawn" }));
      }),
    );
    const report = makeReport();
    const { user } = renderWithProviders(<WithdrawReport report={report} />);

    await user.click(
      screen.getByRole("button", { name: "Withdraw my report" }),
    );
    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    expect(await screen.findByText("Report withdrawn")).toBeInTheDocument();
    expect(called).toBe(true);
  });

  it("explains when the API refuses", async () => {
    server.use(
      http.post(`${API}/reports/rep-1/withdraw`, () =>
        HttpResponse.json(
          {
            error: {
              code: "invalid_transition",
              message: "No",
              details: { reason: "issue_resolved" },
            },
          },
          { status: 422 },
        ),
      ),
    );
    const { user } = renderWithProviders(
      <WithdrawReport report={makeReport()} />,
    );
    await user.click(
      screen.getByRole("button", { name: "Withdraw my report" }),
    );
    await user.click(screen.getByRole("button", { name: "Withdraw" }));
    expect(
      await screen.findByText(/can't be withdrawn now/),
    ).toBeInTheDocument();
  });

  it("isn't offered once the issue is resolved, and says so when withdrawn", () => {
    const base = makeReport();
    const { rerender } = renderWithProviders(
      <WithdrawReport
        report={{
          ...base,
          issue: base.issue ? { ...base.issue, status: "resolved" } : null,
        }}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    rerender(<WithdrawReport report={{ ...base, status: "withdrawn" }} />);
    expect(screen.getByText(/You withdrew this report/)).toBeInTheDocument();
  });
});
