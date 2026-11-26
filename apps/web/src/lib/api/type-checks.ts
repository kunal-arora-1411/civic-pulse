/*
 * Compile-time checks that hand-kept constants still match the generated
 * client. `expectType<Same<A, B>>(true)` fails typecheck when A and B
 * differ, so `pnpm gen:api` after a spec change points at what to update.
 */
export type Same<A, B> = [A] extends [B]
  ? [B] extends [A]
    ? true
    : false
  : false;

export function expectType<T extends true>(_value: T): void {}
