import {
  adminCreateCategory,
  adminListCategories,
  adminUpdateCategory,
  categoriesList,
} from "@civicpulse/api-client";
import { call } from "../generated-client";
import { type Paginated, paginated } from "../schemas";
import {
  type Category,
  type CategoryField,
  categorySchema,
  type I18nText,
} from "../schemas-phase1";

/**
 * Active categories for the report form, ordered by `sort_order`. Public:
 * works with just the tenant header.
 */
export function listCategories(signal?: AbortSignal): Promise<Category[]> {
  return call(categorySchema.array(), (o) => categoriesList(o), { signal });
}

export function listAdminCategories(
  signal?: AbortSignal,
): Promise<Paginated<Category>> {
  return call(
    paginated(categorySchema),
    (o) => adminListCategories({ limit: 100 }, o),
    { signal },
  );
}

export type CategoryInput = {
  code: string;
  name_i18n: I18nText;
  description_i18n?: I18nText;
  icon: string | null;
  evidence: { min_photos: number; max_photos: number };
  fields: CategoryField[];
  default_department_id?: string | null;
  sort_order: number;
  is_active: boolean;
};

/** Creating needs an icon (CategoryCreate); only an update may clear it. */
export type CreateCategoryInput = CategoryInput & { icon: string };

export function createCategory(body: CreateCategoryInput): Promise<Category> {
  return call(categorySchema, (o) => adminCreateCategory(body, o));
}

export function updateCategory(
  id: string,
  body: Partial<CategoryInput>,
): Promise<Category> {
  return call(categorySchema, (o) => adminUpdateCategory(id, body, o));
}
