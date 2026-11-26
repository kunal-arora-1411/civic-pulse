/*
 * Load test for the common reads (P6-08): p95 under 500 ms.
 *
 *   k6 run -e API_URL=http://localhost:8000 -e TENANT=demo-city infra/load/reads.js
 *
 * Two scenarios run together:
 *   public  anonymous visitors on the tracker (list, map, detail, scorecard)
 *   staff   signed-in operators on the console (issue list, map, detail)
 *
 * Run it against a seeded stack with DEV_FIXED_OTP=true (staff sign in with
 * the dev code), and from one machine raise the per-address limits, or every
 * virtual user shares one address and gets 429s:
 *   PUBLIC_MAX_PER_IP_PER_MINUTE=1000000 TENANT_LOOKUP_MAX_PER_IP_PER_MINUTE=1000000
 *   OTP_MAX_PER_IP_PER_HOUR=1000000 OTP_VERIFY_MAX_PER_IP_PER_HOUR=1000000
 * Never raise them in production.
 *
 * Tune the load with PUBLIC_RATE and STAFF_VUS; the defaults are a guess
 * at a pilot city's peak (two wards), to be replaced by the agreed figure.
 */
import { check, fail } from "k6";
import http from "k6/http";
import { Trend } from "k6/metrics";

const API = `${__ENV.API_URL || "http://localhost:8000"}/api/v1`;
const TENANT = __ENV.TENANT || "demo-city";
const STAFF_PHONE = __ENV.STAFF_PHONE || "+919000000002"; // seeded operator
const DEV_OTP = __ENV.DEV_OTP || "000000";
const DURATION = __ENV.DURATION || "3m";

const publicReads = new Trend("public_read_duration", true);
const staffReads = new Trend("staff_read_duration", true);

export const options = {
  scenarios: {
    public: {
      executor: "constant-arrival-rate",
      exec: "publicVisitor",
      rate: Number(__ENV.PUBLIC_RATE || 50), // iterations per second
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
    staff: {
      executor: "constant-vus",
      exec: "staffMember",
      vus: Number(__ENV.STAFF_VUS || 20),
      duration: DURATION,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    public_read_duration: ["p(95)<500"],
    staff_read_duration: ["p(95)<500"],
  },
};

function get(url, params, trend) {
  const res = http.get(url, params);
  trend.add(res.timings.duration);
  check(res, { "status is 200": (r) => r.status === 200 });
  return res;
}

export function setup() {
  const headers = { "Content-Type": "application/json", "X-Tenant": TENANT };
  const requested = http.post(
    `${API}/auth/otp/request`,
    JSON.stringify({ phone: STAFF_PHONE }),
    { headers },
  );
  if (requested.status !== 200) fail(`OTP request: ${requested.status}`);
  const verified = http.post(
    `${API}/auth/otp/verify`,
    JSON.stringify({ challenge_id: requested.json("challenge_id"), code: DEV_OTP }),
    { headers },
  );
  const token = verified.json("access_token");
  if (!token) fail(`OTP verify: ${verified.status} (is DEV_FIXED_OTP on, MFA off?)`);

  const pub = http.get(`${API}/public/${TENANT}/issues?limit=50`);
  const issueIds = (pub.json("items") || []).map((i) => i.id);
  if (!issueIds.length) fail("No public issues: seed the stack first.");
  return { token, issueIds };
}

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

export function publicVisitor({ issueIds }) {
  const base = `${API}/public/${TENANT}`;
  get(`${base}/issues?limit=20`, {}, publicReads);
  get(`${base}/issues/geojson`, {}, publicReads);
  get(`${base}/issues/${pick(issueIds)}`, {}, publicReads);
  if (Math.random() < 0.2) get(`${base}/scorecard`, {}, publicReads);
}

export function staffMember({ token, issueIds }) {
  const params = {
    headers: { Authorization: `Bearer ${token}`, "X-Tenant": TENANT },
  };
  get(`${API}/issues?limit=25&sort=-priority`, params, staffReads);
  get(`${API}/issues/geojson`, params, staffReads);
  get(`${API}/issues/${pick(issueIds)}`, params, staffReads);
  get(`${API}/tenants/current`, params, staffReads);
}
