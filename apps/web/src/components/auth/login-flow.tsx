"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowLeft,
  KeyRound,
  MessageSquareText,
  Smartphone,
} from "lucide-react";
import { hasLocale, useLocale, useTranslations } from "next-intl";
import {
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { formatSeconds, useCountdown } from "@/hooks/use-countdown";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useRouter } from "@/i18n/navigation";
import { locales } from "@/i18n/routing";
import {
  completeLogin,
  isApiError,
  type OtpChallenge,
  requestOtp,
  type TokenResponse,
  verifyMfa,
  verifyOtp,
} from "@/lib/api";
import { homePathFor, safeNextPath } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { maskIndianPhone, normalizeIndianPhone } from "@/lib/phone";
import { CODE_LENGTH, CodeInput } from "./code-input";

type Step =
  | { kind: "phone"; notice?: string }
  | {
      kind: "otp";
      phone: string;
      challengeId: string;
      resendAt: number;
      expiresAt: number;
    }
  | { kind: "mfa"; mfaToken: string }
  | { kind: "done" };

function challengeStep(phone: string, challenge: OtpChallenge): Step {
  const now = Date.now();
  return {
    kind: "otp",
    phone,
    challengeId: challenge.challenge_id,
    resendAt: now + challenge.resend_after * 1000,
    expiresAt: now + challenge.expires_in * 1000,
  };
}

function nextPathFromLocation(): string | null {
  if (typeof window === "undefined") return null;
  return safeNextPath(new URLSearchParams(window.location.search).get("next"));
}

/**
 * Phone → OTP → (MFA) sign-in. `?next=` is read from `window.location` at
 * the moment of redirect rather than through useSearchParams, which would
 * suspend during prerendering and push the whole form out of the static
 * shell.
 */
export function LoginFlow() {
  const t = useTranslations("login");
  const router = useRouter();
  const locale = useLocale();
  const { status, user } = useSession();
  const [step, setStep] = useState<Step>({ kind: "phone" });

  // With Cache Components the page stays mounted (hidden) after we
  // navigate away. Reset on hide so returning after sign-out starts fresh.
  useLayoutEffect(() => () => setStep({ kind: "phone" }), []);

  // Already signed in (or just finished): leave the login page, switching
  // to the language saved on the account if it differs from the current one.
  useEffect(() => {
    if (status !== "authenticated" || !user) return;
    const target = nextPathFromLocation() ?? homePathFor(user);
    if (user.locale !== locale && hasLocale(locales, user.locale)) {
      router.replace(target, { locale: user.locale });
    } else {
      router.replace(target);
    }
  }, [status, user, router, locale]);

  const finish = (tokens: TokenResponse) => {
    setStep({ kind: "done" });
    completeLogin(tokens);
  };

  switch (step.kind) {
    case "phone":
      return (
        <PhoneStep
          notice={step.notice}
          onSent={(phone, challenge) =>
            setStep(challengeStep(phone, challenge))
          }
        />
      );
    case "otp":
      return (
        <OtpStep
          step={step}
          onBack={() => setStep({ kind: "phone" })}
          onResent={(challenge) =>
            setStep(challengeStep(step.phone, challenge))
          }
          onMfa={(mfaToken) => setStep({ kind: "mfa", mfaToken })}
          onSignedIn={finish}
        />
      );
    case "mfa":
      return (
        <MfaStep
          mfaToken={step.mfaToken}
          onRestart={(notice) => setStep({ kind: "phone", notice })}
          onSignedIn={finish}
        />
      );
    case "done":
      return (
        <output className="block text-center text-muted-foreground">
          {t("signedIn")}
        </output>
      );
  }
}

function StepHeader({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <span className="grid size-11 place-items-center rounded-xl bg-primary-soft text-primary-soft-foreground [&_svg]:size-5">
        {icon}
      </span>
      <h1 className="text-2xl font-semibold">{title}</h1>
      {children ? (
        <div className="text-[0.9375rem] text-muted-foreground">{children}</div>
      ) : null}
    </div>
  );
}

function PhoneStep({
  notice,
  onSent,
}: {
  notice?: string;
  onSent: (phone: string, challenge: OtpChallenge) => void;
}) {
  const t = useTranslations("login");
  const errorMessage = useErrorMessage();

  const schema = z.object({
    phone: z
      .string()
      .trim()
      .min(1, t("phoneRequired"))
      .refine(
        (value) => normalizeIndianPhone(value) !== null,
        t("phoneInvalid"),
      ),
  });
  const form = useForm<z.input<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { phone: "" },
  });

  const request = useMutation({
    mutationFn: (phone: string) => requestOtp(phone),
    onSuccess: (challenge, phone) => onSent(phone, challenge),
  });

  const onSubmit = form.handleSubmit(({ phone }) => {
    const normalized = normalizeIndianPhone(phone);
    if (normalized) request.mutate(normalized);
  });

  const fieldError = form.formState.errors.phone?.message;

  return (
    <form onSubmit={onSubmit} noValidate className="grid gap-6">
      <StepHeader icon={<Smartphone aria-hidden="true" />} title={t("title")}>
        {t("phoneStepHint")}
      </StepHeader>

      {notice ? (
        <Alert variant="warning" live="polite">
          {notice}
        </Alert>
      ) : null}

      <Field
        label={t("phoneLabel")}
        description={t("phoneDescription")}
        error={fieldError}
        required
      >
        {(control) => (
          <div className="flex">
            <span
              aria-hidden="true"
              className="inline-flex items-center rounded-s-lg border border-e-0 border-input bg-muted px-3 font-mono text-[0.9375rem] text-muted-foreground"
            >
              +91
            </span>
            <Input
              {...control}
              {...form.register("phone")}
              type="tel"
              inputMode="tel"
              autoComplete="tel-national"
              placeholder="98765 43210"
              className="h-12 rounded-s-none font-mono text-lg tracking-wide"
            />
          </div>
        )}
      </Field>

      {request.isError ? (
        <Alert variant="destructive" live="assertive">
          {errorMessage(request.error)}
        </Alert>
      ) : null}

      <Button type="submit" size="lg" loading={request.isPending}>
        {t("sendCode")}
      </Button>
    </form>
  );
}

function useCodeError() {
  const t = useTranslations("login");
  const errorMessage = useErrorMessage();
  return (
    error: unknown,
  ): { field?: string; form?: string; expired?: boolean } => {
    if (isApiError(error, "invalid_code")) {
      const remaining = error.details.attempts_remaining;
      const suffix =
        typeof remaining === "number"
          ? ` ${t("attemptsRemaining", { count: remaining })}`
          : "";
      return { field: `${errorMessage(error)}${suffix}` };
    }
    if (isApiError(error, "code_expired")) return { expired: true };
    return { form: errorMessage(error) };
  };
}

function OtpStep({
  step,
  onBack,
  onResent,
  onMfa,
  onSignedIn,
}: {
  step: Extract<Step, { kind: "otp" }>;
  onBack: () => void;
  onResent: (challenge: OtpChallenge) => void;
  onMfa: (mfaToken: string) => void;
  onSignedIn: (tokens: TokenResponse) => void;
}) {
  const t = useTranslations("login");
  const errorMessage = useErrorMessage();
  const describeError = useCodeError();
  const [code, setCode] = useState("");
  const [formatError, setFormatError] = useState<string | null>(null);
  const [resentNotice, setResentNotice] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const resendIn = useCountdown(step.resendAt);
  const expiresIn = useCountdown(step.expiresAt);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const verify = useMutation({
    mutationFn: (value: string) =>
      verifyOtp({ challenge_id: step.challengeId, code: value }),
    onSuccess: (result) => {
      if ("mfa_required" in result) onMfa(result.mfa_token);
      else onSignedIn(result);
    },
    onError: () => {
      setCode("");
      inputRef.current?.focus();
    },
  });

  const resend = useMutation({
    mutationFn: () => requestOtp(step.phone),
    onSuccess: (challenge) => {
      verify.reset();
      setCode("");
      setResentNotice(true);
      onResent(challenge);
      inputRef.current?.focus();
    },
  });

  const submit = (value: string) => {
    if (value.length !== CODE_LENGTH) {
      setFormatError(t("codeInvalidFormat"));
      inputRef.current?.focus();
      return;
    }
    setFormatError(null);
    setResentNotice(false);
    verify.mutate(value);
  };

  const verifyError = verify.isError ? describeError(verify.error) : null;
  const expired = expiresIn === 0 || Boolean(verifyError?.expired);

  return (
    <form
      noValidate
      className="grid gap-6"
      onSubmit={(event) => {
        event.preventDefault();
        submit(code);
      }}
    >
      <StepHeader
        icon={<MessageSquareText aria-hidden="true" />}
        title={t("otpStepTitle")}
      >
        <p>
          {t("otpSentTo", { phone: maskIndianPhone(step.phone) })}{" "}
          <Button variant="link" onClick={onBack} className="font-semibold">
            {t("changeNumber")}
          </Button>
        </p>
      </StepHeader>

      {expired ? (
        <Alert variant="warning" live="assertive" title={t("codeExpiredTitle")}>
          {t("codeExpiredBody")}
        </Alert>
      ) : null}

      <Field
        label={t("otpLabel")}
        error={formatError ?? verifyError?.field}
        description={
          expired
            ? undefined
            : t("expiresIn", { time: formatSeconds(expiresIn) })
        }
        required
      >
        {(control) => (
          <CodeInput
            {...control}
            ref={inputRef}
            value={code}
            disabled={expired}
            onValueChange={(value) => {
              setCode(value);
              if (formatError) setFormatError(null);
            }}
            onComplete={submit}
          />
        )}
      </Field>

      {verifyError?.form ? (
        <Alert variant="destructive" live="assertive">
          {verifyError.form}
        </Alert>
      ) : null}
      {resend.isError ? (
        <Alert variant="destructive" live="assertive">
          {errorMessage(resend.error)}
        </Alert>
      ) : null}
      <output className="sr-only">{resentNotice ? t("codeResent") : ""}</output>

      <div className="grid gap-3">
        <Button
          type="submit"
          size="lg"
          loading={verify.isPending}
          disabled={expired}
        >
          {t("verify")}
        </Button>
        <Button
          variant="ghost"
          onClick={() => resend.mutate()}
          disabled={resendIn > 0}
          loading={resend.isPending}
        >
          {resendIn > 0
            ? t("resendIn", { time: formatSeconds(resendIn) })
            : t("resend")}
        </Button>
      </div>
    </form>
  );
}

function MfaStep({
  mfaToken,
  onRestart,
  onSignedIn,
}: {
  mfaToken: string;
  onRestart: (notice?: string) => void;
  onSignedIn: (tokens: TokenResponse) => void;
}) {
  const t = useTranslations("login");
  const describeError = useCodeError();
  const [code, setCode] = useState("");
  const [formatError, setFormatError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const verify = useMutation({
    mutationFn: (value: string) =>
      verifyMfa({ mfa_token: mfaToken, code: value }),
    onSuccess: onSignedIn,
    onError: (error) => {
      if (isApiError(error, "code_expired")) {
        onRestart(t("mfaExpired"));
        return;
      }
      setCode("");
      inputRef.current?.focus();
    },
  });

  const submit = (value: string) => {
    if (value.length !== CODE_LENGTH) {
      setFormatError(t("codeInvalidFormat"));
      inputRef.current?.focus();
      return;
    }
    setFormatError(null);
    verify.mutate(value);
  };

  const verifyError = verify.isError ? describeError(verify.error) : null;

  return (
    <form
      noValidate
      className="grid gap-6"
      onSubmit={(event) => {
        event.preventDefault();
        submit(code);
      }}
    >
      <StepHeader
        icon={<KeyRound aria-hidden="true" />}
        title={t("mfaStepTitle")}
      >
        {t("mfaStepHint")}
      </StepHeader>

      <Field
        label={t("mfaLabel")}
        error={formatError ?? verifyError?.field}
        required
      >
        {(control) => (
          <CodeInput
            {...control}
            ref={inputRef}
            value={code}
            onValueChange={(value) => {
              setCode(value);
              if (formatError) setFormatError(null);
            }}
            onComplete={submit}
          />
        )}
      </Field>

      {verifyError?.form ? (
        <Alert variant="destructive" live="assertive">
          {verifyError.form}
        </Alert>
      ) : null}

      <div className="grid gap-3">
        <Button type="submit" size="lg" loading={verify.isPending}>
          {t("verify")}
        </Button>
        <Button variant="ghost" onClick={() => onRestart()}>
          <ArrowLeft aria-hidden="true" />
          {t("startOver")}
        </Button>
      </div>
    </form>
  );
}
