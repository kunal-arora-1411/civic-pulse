import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";
import { ToastProvider } from "@/components/ui/toast";
import messages from "../../messages/en.json";

/**
 * Render with the same providers the app uses: English messages, a fresh
 * query client per test (no retries, so failures surface immediately)
 * and the toast region.
 */
export function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <NextIntlClientProvider
      locale="en"
      messages={messages}
      timeZone="Asia/Kolkata"
    >
      <QueryClientProvider client={queryClient}>
        <ToastProvider dismissLabel="Dismiss">{children}</ToastProvider>
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
  return {
    user: userEvent.setup(),
    queryClient,
    ...render(ui, { wrapper }),
  };
}
