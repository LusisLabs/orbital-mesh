import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AuthScreen, authCallbackErrorMessage, authFailureMessage } from "./ProductApp";
import type { AuthConfig } from "./api";

const authConfig: AuthConfig = {
  auth_mode: "app_session",
  signup_enabled: true,
  password_auth_enabled: true,
  captcha: {
    provider: "disabled",
    site_key: "",
    configured: false,
    dev_bypass_enabled: true,
  },
  oauth: {
    google: { configured: true },
    github: { configured: true },
  },
  invite: {
    required: false,
    configured: false,
    allowlist_enabled: false,
  },
};

function openingButtonTag(html: string, label: string): string {
  const labelIndex = html.indexOf(label);
  expect(labelIndex).toBeGreaterThan(-1);
  const tagStart = html.lastIndexOf("<button", labelIndex);
  const tagEnd = html.indexOf(">", tagStart);
  return html.slice(tagStart, tagEnd + 1);
}

describe("AuthScreen degraded API states", () => {
  it("shows backend-unavailable session probe failures and disables provider actions", () => {
    const html = renderToStaticMarkup(
      <AuthScreen
        config={authConfig}
        sessionState={{ state: "backend-unavailable", message: "Mesh API timed out at http://127.0.0.1:8787" }}
        onSession={() => undefined}
      />,
    );

    expect(html).toContain("Mesh API timed out at http://127.0.0.1:8787");
    expect(openingButtonTag(html, "Continue with Google")).toContain("disabled");
    expect(openingButtonTag(html, "Continue with GitHub")).toContain("disabled");
  });

  it("does not treat an unauthenticated session probe as an API outage", () => {
    const html = renderToStaticMarkup(
      <AuthScreen
        config={authConfig}
        sessionState={{ state: "unauthorized", message: "not authenticated" }}
        onSession={() => undefined}
      />,
    );

    expect(html).not.toContain("not authenticated");
    expect(openingButtonTag(html, "Continue with Google")).not.toContain("disabled");
    expect(openingButtonTag(html, "Continue with GitHub")).not.toContain("disabled");
  });
});

describe("AuthScreen provider proof states", () => {
  it("hides unconfigured provider buttons from the partner-facing screen", () => {
    const html = renderToStaticMarkup(
      <AuthScreen
        config={{
          ...authConfig,
          oauth: {
            google: { configured: false },
            github: { configured: false },
          },
        }}
        sessionState={{ state: "unauthorized", message: "not authenticated" }}
        onSession={() => undefined}
      />,
    );

    expect(html).not.toContain("Continue with Google");
    expect(html).not.toContain("Continue with GitHub");
    expect(html).toContain("Use your invited email and password");
  });

  it("maps OAuth callback failure codes to clear operator-facing messages", () => {
    expect(authCallbackErrorMessage("missing_oauth_code")).toContain("did not include a provider code");
    expect(authCallbackErrorMessage("google_oauth_failed")).toContain("Google OAuth callback failed");
    expect(authCallbackErrorMessage("github_oauth_failed")).toContain("GitHub OAuth callback failed");
  });

  it("maps infra-shaped signup failures to invitation-safe copy", () => {
    expect(authFailureMessage(new Error("captcha verification failed"))).toContain("verification challenge");
    expect(authFailureMessage(new Error("email is not invite allowlisted"))).toContain("not invited");
    expect(authFailureMessage(new Error("user already exists"))).toContain("Log in instead");
  });
});
