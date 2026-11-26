/*
 * Public surface of the API layer. Feature code imports from "@/lib/api"
 * only, never from the files behind it, so swapping the hand-written
 * schemas and endpoints for an orval-generated client means changing what
 * this file re-exports, not every call site.
 */
export { apiDownload, apiRequest, refreshSession } from "./client";
export { API_BASE, API_URL, TENANT } from "./config";
export * from "./endpoints/admin";
export * from "./endpoints/ai";
export * from "./endpoints/analytics";
export * from "./endpoints/auth";
export * from "./endpoints/categories";
export * from "./endpoints/community";
export * from "./endpoints/field";
export * from "./endpoints/issues";
export * from "./endpoints/media";
export * from "./endpoints/notifications";
export * from "./endpoints/operations";
export * from "./endpoints/reports";
export * from "./endpoints/review";
export * from "./endpoints/sla";
export * from "./endpoints/tenant";
export * from "./endpoints/users";
export { ApiError, type ErrorCode, isApiError } from "./errors";
export * from "./schemas";
export * from "./schemas-ai";
export * from "./schemas-analytics";
export * from "./schemas-community";
export * from "./schemas-notifications";
export * from "./schemas-operations";
export * from "./schemas-phase1";
export * from "./schemas-phase2";
export * from "./schemas-sla";
export { type SessionSnapshot, type SessionStatus, session } from "./session";
