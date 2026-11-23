import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isApiError } from "@/lib/api";
import { FakeXhr, nextXhr } from "@/test/fake-xhr";
import { API, server } from "@/test/msw";
import { prepareImage, sha256Hex, uploadImage } from "./upload";

const compress = vi.hoisted(() => vi.fn());
vi.mock("browser-image-compression", () => ({ default: compress }));

const STORAGE = "http://storage.test/bucket/object?signature=abc";

function ticket(id = "upload-1") {
  return {
    upload_id: id,
    method: "PUT",
    url: STORAGE,
    headers: { "Content-Type": "image/jpeg" },
    expires_in: 600,
    max_size_bytes: 10 * 1024 * 1024,
  };
}

const asset = {
  id: "media-1",
  status: "processing",
  content_type: "image/jpeg",
  width: 1200,
  height: 1600,
  variants: { thumb: null, display: null },
  captured_at: null,
};

const image = () => ({
  blob: new Blob([new Uint8Array(4096)], { type: "image/jpeg" }),
  contentType: "image/jpeg" as const,
});

beforeEach(() => {
  FakeXhr.reset();
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
});
afterEach(() => vi.unstubAllGlobals());

describe("uploadImage", () => {
  it("creates the upload, PUTs with progress and completes it", async () => {
    let createBody: Record<string, unknown> | undefined;
    server.use(
      http.post(`${API}/media/uploads`, async ({ request }) => {
        createBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(ticket(), { status: 201 });
      }),
      http.post(`${API}/media/uploads/upload-1/complete`, () =>
        HttpResponse.json(asset),
      ),
    );
    const progress: number[] = [];
    const stages: string[] = [];
    const input = image();

    const result = uploadImage(input, {
      onProgress: (fraction) => progress.push(fraction),
      onStage: (stage) => stages.push(stage),
    });

    const xhr = await nextXhr(1);
    expect(xhr.method).toBe("PUT");
    expect(xhr.url).toBe(STORAGE);
    expect(xhr.headers).toEqual({ "Content-Type": "image/jpeg" });
    expect(xhr.body).toBe(input.blob);

    xhr.progress(1024, 4096);
    xhr.progress(3072, 4096);
    xhr.respond(200);

    await expect(result).resolves.toMatchObject({ id: "media-1" });
    expect(progress).toEqual([0, 0.25, 0.75, 1]);
    expect(stages).toEqual(["preparing", "uploading", "verifying"]);
    expect(createBody).toEqual({
      purpose: "report_evidence",
      content_type: "image/jpeg",
      size_bytes: 4096,
      checksum_sha256: await sha256Hex(input.blob),
    });
  });

  it("fails with upload_failed when storage rejects the PUT, and a retry starts over with a new ticket", async () => {
    let created = 0;
    const completed: string[] = [];
    server.use(
      http.post(`${API}/media/uploads`, () => {
        created += 1;
        return HttpResponse.json(ticket(`upload-${created}`), { status: 201 });
      }),
      http.post(`${API}/media/uploads/:id/complete`, ({ params }) => {
        completed.push(String(params.id));
        return HttpResponse.json(asset);
      }),
    );
    const input = image();

    const first = uploadImage(input);
    (await nextXhr(1)).respond(403);
    const error = await first.catch((e: unknown) => e);
    expect(isApiError(error, "upload_failed")).toBe(true);
    expect(completed).toEqual([]);

    const retry = uploadImage(input);
    (await nextXhr(2)).respond(200);
    await expect(retry).resolves.toMatchObject({ id: "media-1" });
    expect(created).toBe(2);
    expect(completed).toEqual(["upload-2"]);
  });

  it("reports a dropped connection as upload_failed with status 0", async () => {
    server.use(
      http.post(`${API}/media/uploads`, () =>
        HttpResponse.json(ticket(), { status: 201 }),
      ),
    );
    const result = uploadImage(image());
    (await nextXhr(1)).networkError();
    await expect(result).rejects.toMatchObject({
      code: "upload_failed",
      status: 0,
    });
  });

  it("surfaces a failed verification from the API", async () => {
    server.use(
      http.post(`${API}/media/uploads`, () =>
        HttpResponse.json(ticket(), { status: 201 }),
      ),
      http.post(`${API}/media/uploads/upload-1/complete`, () =>
        HttpResponse.json(
          {
            error: {
              code: "upload_verification_failed",
              message: "Checksum mismatch",
            },
          },
          { status: 422 },
        ),
      ),
    );
    const result = uploadImage(image());
    (await nextXhr(1)).respond(200);
    await expect(result).rejects.toMatchObject({
      code: "upload_verification_failed",
    });
  });

  it("aborts the PUT when the photo is removed mid-upload", async () => {
    server.use(
      http.post(`${API}/media/uploads`, () =>
        HttpResponse.json(ticket(), { status: 201 }),
      ),
    );
    const controller = new AbortController();
    const result = uploadImage(image(), { signal: controller.signal });
    const xhr = await nextXhr(1);
    controller.abort();
    expect(xhr.aborted).toBe(true);
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
  });

  it("refuses files over the limit before asking for a ticket", async () => {
    const big = {
      blob: new Blob([new Uint8Array(10 * 1024 * 1024 + 1)]),
      contentType: "image/jpeg" as const,
    };
    await expect(uploadImage(big)).rejects.toMatchObject({
      code: "file_too_large",
    });
  });
});

describe("prepareImage", () => {
  it("compresses to a ~1600 px JPEG at quality 0.8", async () => {
    const out = new File([new Uint8Array(10)], "small.jpg", {
      type: "image/jpeg",
    });
    compress.mockResolvedValue(out);
    const photo = new File([new Uint8Array(100)], "IMG_1.jpg", {
      type: "image/jpeg",
    });

    await expect(prepareImage(photo)).resolves.toEqual({
      blob: out,
      contentType: "image/jpeg",
    });
    expect(compress).toHaveBeenCalledWith(
      photo,
      expect.objectContaining({
        maxWidthOrHeight: 1600,
        initialQuality: 0.8,
        fileType: "image/jpeg",
        useWebWorker: false,
      }),
    );
  });

  it("falls back to the original when the browser can't decode it", async () => {
    compress.mockRejectedValue(new Error("decode failed"));
    const png = new File([new Uint8Array(10)], "map.png", {
      type: "image/png",
    });
    await expect(prepareImage(png)).resolves.toEqual({
      blob: png,
      contentType: "image/png",
    });
  });

  it("rejects formats the API won't take", async () => {
    compress.mockRejectedValue(new Error("decode failed"));
    const heic = new File([new Uint8Array(10)], "IMG.heic", {
      type: "image/heic",
    });
    await expect(prepareImage(heic)).rejects.toMatchObject({
      code: "unsupported_media_type",
    });
    const pdf = new File([new Uint8Array(10)], "doc.pdf", {
      type: "application/pdf",
    });
    await expect(prepareImage(pdf)).rejects.toMatchObject({
      code: "unsupported_media_type",
    });
  });
});
