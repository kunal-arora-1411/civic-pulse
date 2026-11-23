/**
 * A minimal XMLHttpRequest stand-in for the storage PUT, so tests control
 * upload progress and the outcome step by step. Install it with
 * `vi.stubGlobal("XMLHttpRequest", FakeXhr)`.
 */
export class FakeXhr {
  static instances: FakeXhr[] = [];

  static reset() {
    FakeXhr.instances = [];
  }

  static last(): FakeXhr {
    const xhr = FakeXhr.instances.at(-1);
    if (!xhr) throw new Error("No XMLHttpRequest was opened");
    return xhr;
  }

  method = "";
  url = "";
  status = 0;
  body: unknown = null;
  headers: Record<string, string> = {};
  aborted = false;
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeXhr.instances.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  send(body: unknown) {
    this.body = body;
  }

  abort() {
    this.aborted = true;
    this.onabort?.();
  }

  // Test controls.

  progress(loaded: number, total: number) {
    this.upload.onprogress?.({
      lengthComputable: true,
      loaded,
      total,
    } as ProgressEvent);
  }

  respond(status: number) {
    this.status = status;
    this.onload?.();
  }

  networkError() {
    this.status = 0;
    this.onerror?.();
  }
}

/** Wait until the pipeline has opened its next XHR. */
export async function nextXhr(count: number): Promise<FakeXhr> {
  for (let i = 0; i < 200; i++) {
    if (FakeXhr.instances.length >= count) return FakeXhr.instances[count - 1];
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(`Expected ${count} XMLHttpRequest(s)`);
}
