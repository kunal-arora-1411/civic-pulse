/*
 * Public surface of the generated client: request functions, zod schemas
 * (with their inferred types) and the mutator hook. Everything under
 * ./generated is written by `pnpm gen:api`; don't edit it by hand.
 */
export * from "./generated/endpoints";
export * from "./generated/schemas";
export {
  configureRequester,
  type HttpMethod,
  type RequestConfig,
  type Requester,
  type RequestOptions,
} from "./mutator";
