import { describe, expect, it } from "vitest";
import { appendTranscript, speechLang } from "./use-speech-input";

describe("appendTranscript", () => {
  it("starts an empty box with the spoken text", () => {
    expect(appendTranscript("", "  deep pothole ")).toBe("deep pothole");
    expect(appendTranscript("   ", "deep pothole")).toBe("deep pothole");
  });

  it("adds one space between typed and spoken text", () => {
    expect(appendTranscript("Near the school.", "bikes swerve")).toBe(
      "Near the school. bikes swerve",
    );
    expect(appendTranscript("Near the school. ", "bikes swerve")).toBe(
      "Near the school. bikes swerve",
    );
  });

  it("ignores empty results", () => {
    expect(appendTranscript("typed", "  ")).toBe("typed");
  });
});

describe("speechLang", () => {
  it("uses the Indian variant of the app locale", () => {
    expect(speechLang("hi")).toBe("hi-IN");
    expect(speechLang("en")).toBe("en-IN");
    expect(speechLang("en-GB")).toBe("en-GB");
  });
});
