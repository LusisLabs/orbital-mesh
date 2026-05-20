const APP_HOST = "app.lusislabs.com";
const MARKETING_HOSTS = new Set(["lusislabs.com", "www.lusislabs.com"]);
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

export function shouldRenderLanding(hostname: string, search = ""): boolean {
  const normalizedHost = hostname.toLowerCase();
  const params = new URLSearchParams(search);
  if (params.get("landing") === "1") return true;
  if (params.get("app") === "1") return false;
  if (normalizedHost === APP_HOST) return false;
  if (LOCAL_HOSTS.has(normalizedHost)) return false;
  return MARKETING_HOSTS.has(normalizedHost);
}
