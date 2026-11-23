import { apiRequest } from "../client";
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
  return apiRequest({
    path: "/categories",
    schema: categorySchema.array(),
    signal,
  });
}

export function listAdminCategories(
  signal?: AbortSignal,
): Promise<Paginated<Category>> {
  return apiRequest({
    path: "/admin/categories",
    query: { limit: 100 },
    schema: paginated(categorySchema),
    signal,
  });
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

export function createCategory(body: CategoryInput): Promise<Category> {
  return apiRequest({
    method: "POST",
    path: "/admin/categories",
    body,
    schema: categorySchema,
  });
}

export function updateCategory(
  id: string,
  body: Partial<CategoryInput>,
): Promise<Category> {
  return apiRequest({
    method: "PATCH",
    path: `/admin/categories/${encodeURIComponent(id)}`,
    body,
    schema: categorySchema,
  });
}
