import { setupServer } from "msw/node";

/**
 * Shared MSW server. Tests register the handlers they need with
 * `server.use(...)`; any request without a handler fails the test, so a
 * forgotten mock can't silently hit the network.
 */
export const server = setupServer();

export const API = "http://api.test/api/v1";
