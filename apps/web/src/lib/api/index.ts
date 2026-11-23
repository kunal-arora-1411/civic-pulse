/*
 * Public surface of the API layer. Feature code imports from "@/lib/api"
 * only, never from the files behind it, so swapping the hand-written
 * schemas and endpoints for an orval-generated client means changing what
 * this file re-exports, not every call site.
 */
export { apiRequest } from "./client";
export { API_BASE, API_URL, TENANT } from "./config";
export * from "./endpoints/admin";
export * from "./endpoints/auth";
export * from "./endpoints/tenant";
export * from "./endpoints/users";
export { ApiError, type ErrorCode, isApiError } from "./errors";
export * from "./schemas";
export { type SessionSnapshot, type SessionStatus, session } from "./session";
