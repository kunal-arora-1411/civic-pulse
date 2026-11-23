import { screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { CategoryField } from "@/lib/api";
import {
  type DraftField,
  fromDraftFields,
  slugifyKey,
  toDraftFields,
  validateFields,
} from "@/lib/categories/fields";
import { renderWithProviders } from "@/test/render";
import { CategoryFieldsEditor } from "./category-fields-editor";

const existing: CategoryField[] = [
  {
    key: "road_name",
    type: "text",
    required: false,
    label_i18n: { en: "Road name", hi: "सड़क का नाम" },
  },
  {
    key: "size",
    type: "select",
    required: true,
    label_i18n: { en: "Size" },
    options: [
      { value: "small", label_i18n: { en: "Small" } },
      { value: "large", label_i18n: { en: "Large", hi: "बड़ा" } },
    ],
  },
];

function Harness({
  initial = [],
  showErrors = false,
  onValue,
}: {
  initial?: CategoryField[];
  showErrors?: boolean;
  onValue?: (fields: DraftField[]) => void;
}) {
  const [fields, setFields] = useState(() => toDraftFields(initial));
  return (
    <CategoryFieldsEditor
      value={fields}
      onChange={(next) => {
        setFields(next);
        onValue?.(next);
      }}
      errors={showErrors ? validateFields(fields) : null}
    />
  );
}

describe("CategoryFieldsEditor", () => {
  it("adds a question and suggests its key from the English label", async () => {
    let latest: DraftField[] = [];
    const { user } = renderWithProviders(
      <Harness onValue={(fields) => (latest = fields)} />,
    );
    expect(screen.getByText(/no extra questions/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add a question" }));
    const question = screen.getByRole("group", { name: /question 1/i });
    await user.type(
      within(question).getByLabelText(/question \(english\)/i),
      "Pole number, if visible",
    );
    await user.type(
      within(question).getByLabelText(/question \(hindi\)/i),
      "खंभा नंबर",
    );

    expect(within(question).getByLabelText(/^key/i)).toHaveValue(
      "pole_number_if_visible",
    );
    expect(fromDraftFields(latest)).toEqual([
      {
        key: "pole_number_if_visible",
        type: "text",
        required: false,
        label_i18n: { en: "Pole number, if visible", hi: "खंभा नंबर" },
      },
    ]);
  });

  it("edits a choice list with options and round-trips the API shape", async () => {
    let latest: DraftField[] = [];
    const { user } = renderWithProviders(
      <Harness initial={existing} onValue={(fields) => (latest = fields)} />,
    );
    const size = screen.getByRole("group", { name: /question 2/i });
    expect(within(size).getAllByLabelText(/stored value/i)).toHaveLength(2);

    await user.click(
      within(size).getByRole("button", { name: "Add a choice" }),
    );
    const values = within(size).getAllByLabelText(/label \(english\)/i);
    await user.type(values[2] as HTMLElement, "Very large");

    expect(fromDraftFields(latest)[1]).toEqual({
      ...existing[1],
      options: [
        ...(existing[1]?.options ?? []),
        { value: "very_large", label_i18n: { en: "Very large" } },
      ],
    });
    // The untouched field comes back exactly as it went in.
    expect(fromDraftFields(latest)[0]).toEqual(existing[0]);
  });

  it("switching to a choice list starts with one empty choice", async () => {
    const { user } = renderWithProviders(
      <Harness initial={[existing[0] as CategoryField]} />,
    );
    const question = screen.getByRole("group", { name: /question 1/i });
    await user.selectOptions(
      within(question).getByLabelText(/answer type/i),
      "select",
    );
    expect(within(question).getAllByLabelText(/stored value/i)).toHaveLength(1);
  });

  it("reorders and removes questions with buttons", async () => {
    let latest: DraftField[] = [];
    const { user } = renderWithProviders(
      <Harness initial={existing} onValue={(fields) => (latest = fields)} />,
    );
    expect(
      screen.getByRole("button", { name: "Move question 1 up" }),
    ).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: "Move question 2 up" }),
    );
    expect(latest.map((field) => field.key)).toEqual(["size", "road_name"]);

    await user.click(screen.getByRole("button", { name: "Remove question 2" }));
    expect(latest.map((field) => field.key)).toEqual(["size"]);
  });

  it("shows validation problems next to the right controls", () => {
    renderWithProviders(
      <Harness
        showErrors
        initial={[
          {
            key: "size",
            type: "text",
            required: false,
            label_i18n: { en: "" },
          },
          {
            key: "size",
            type: "select",
            required: false,
            label_i18n: { en: "Size" },
            options: [
              { value: "a", label_i18n: { en: "A" } },
              { value: "a", label_i18n: { en: "" } },
            ],
          },
        ]}
      />,
    );
    const first = screen.getByRole("group", { name: /question 1/i });
    expect(
      within(first).getByText("Another question already uses this key."),
    ).toBeInTheDocument();
    expect(
      within(first).getByText("Enter the question in English."),
    ).toBeInTheDocument();
    const second = screen.getByRole("group", { name: /question 2/i });
    expect(
      within(second).getAllByText("Each choice needs a different value."),
    ).toHaveLength(2);
    expect(
      within(second).getByText("Enter an English label."),
    ).toBeInTheDocument();
  });
});

describe("field helpers", () => {
  it("validates keys", () => {
    const [field] = toDraftFields([existing[0] as CategoryField]);
    const check = (key: string) =>
      validateFields([{ ...(field as DraftField), key }])[
        (field as DraftField).id
      ]?.field ?? [];
    expect(check("road_name")).toEqual([]);
    expect(check("")).toEqual(["key_required"]);
    expect(check("Road Name")).toEqual(["key_format"]);
    expect(check("9lives")).toEqual(["key_format"]);
  });

  it("requires at least one choice for a choice list", () => {
    const [field] = toDraftFields([
      { ...(existing[1] as CategoryField), options: [] },
    ]);
    expect(
      validateFields([field as DraftField])[(field as DraftField).id]?.field,
    ).toEqual(["options_required"]);
  });

  it("slugifies labels into keys", () => {
    expect(slugifyKey("Approximate depth (cm)")).toBe("approximate_depth_cm");
    expect(slugifyKey("2nd floor?")).toBe("f_2nd_floor");
    expect(slugifyKey("गड्ढा")).toBe("");
  });
});
