import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import { PhotosStep } from "./photos-step";

const limits = { min: 1, max: 5 };

function renderStep(onAdd = vi.fn()) {
  const view = renderWithProviders(
    <PhotosStep
      photos={[]}
      limits={limits}
      issue={null}
      onAdd={onAdd}
      onRemove={vi.fn()}
      onRetry={vi.fn()}
    />,
  );
  return { ...view, onAdd };
}

function stubCamera(getUserMedia: () => Promise<MediaStream>) {
  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value: true,
  });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(getUserMedia),
      enumerateDevices: vi.fn(async () => [{ kind: "videoinput" }]),
    },
  });
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "mediaDevices");
  Reflect.deleteProperty(window, "isSecureContext");
});

describe("Take a photo", () => {
  beforeEach(() => {
    HTMLMediaElement.prototype.play = vi.fn(async () => undefined);
  });

  it("falls back to the file input when the page can't open a camera", async () => {
    const { user, container } = renderStep();
    const input = container.querySelector<HTMLInputElement>(
      'input[capture="environment"]',
    );
    if (!input) throw new Error("camera input missing");
    const click = vi.spyOn(input, "click");

    await user.click(screen.getByRole("button", { name: "Take a photo" }));

    expect(click).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the camera in the page and asks for the back camera", async () => {
    const track = { stop: vi.fn() };
    stubCamera(
      async () => ({ getTracks: () => [track] }) as unknown as MediaStream,
    );
    const { user } = renderStep();

    await user.click(screen.getByRole("button", { name: "Take a photo" }));

    const dialog = await screen.findByRole("dialog", { name: "Take a photo" });
    expect(dialog).toBeInTheDocument();
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith(
      expect.objectContaining({
        audio: false,
        video: expect.objectContaining({
          facingMode: { ideal: "environment" },
        }),
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Take photo" })).toBeEnabled(),
    );

    await user.click(screen.getByRole("button", { name: "Close the camera" }));
    expect(track.stop).toHaveBeenCalled();
  });

  it("explains a blocked camera and offers a photo file instead", async () => {
    stubCamera(async () => {
      throw new DOMException("denied", "NotAllowedError");
    });
    const { user, container } = renderStep();
    const input = container.querySelector<HTMLInputElement>(
      'input[capture="environment"]',
    );
    if (!input) throw new Error("camera input missing");
    const click = vi.spyOn(input, "click");

    await user.click(screen.getByRole("button", { name: "Take a photo" }));

    expect(await screen.findByText(/Camera access is blocked/)).toBeVisible();
    await act(async () => {
      await user.click(
        screen.getByRole("button", { name: "Choose a photo file" }),
      );
    });
    expect(click).toHaveBeenCalled();
  });
});
