import {
  CommentList,
  CommentOut,
  commentsFlag,
  issuesCommentsCreate,
  issuesCommentsList,
  ModerationItem,
  ModerationPage,
  moderationCommentsDecide,
  moderationCommentsList,
} from "@civicpulse/api-client";
import type { z } from "zod";
import { call } from "../generated-client";

/*
 * Citizen comments held for moderation, and the moderation queue
 * (docs/api/phase-3-contract.md §12).
 */

export type IssueComment = z.infer<typeof CommentOut>;
export type CommentState = IssueComment["state"];
export type ModerationEntry = z.infer<typeof ModerationItem>;
export type ModerationList = z.infer<typeof ModerationPage>;

export function listIssueComments(
  issueId: string,
  signal?: AbortSignal,
): Promise<z.infer<typeof CommentList>> {
  return call(CommentList, (o) => issuesCommentsList(issueId, o), { signal });
}

/** Pending until a moderator approves it; 10 a day per citizen. */
export function addIssueComment(
  issueId: string,
  body: string,
): Promise<IssueComment> {
  return call(CommentOut, (o) => issuesCommentsCreate(issueId, { body }, o));
}

export function flagComment(commentId: string): Promise<IssueComment> {
  return call(CommentOut, (o) => commentsFlag(commentId, o));
}

export function listModerationQueue(
  params: { state?: CommentState; limit?: number; offset?: number },
  signal?: AbortSignal,
): Promise<ModerationList> {
  return call(ModerationPage, (o) => moderationCommentsList(params, o), {
    signal,
  });
}

export function moderateComment(
  commentId: string,
  body: { decision: "approve" | "reject"; reason?: string },
): Promise<ModerationEntry> {
  return call(ModerationItem, (o) =>
    moderationCommentsDecide(commentId, body, o),
  );
}
