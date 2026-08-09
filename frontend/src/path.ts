const configuredBase = (import.meta.env.VITE_APP_BASE_PATH || "").trim();
export const APP_BASE_PATH = configuredBase.replace(/\/+$/, "");

export function appPathname(): string {
  const pathname = window.location.pathname;
  if (APP_BASE_PATH && (pathname === APP_BASE_PATH || pathname.startsWith(`${APP_BASE_PATH}/`))) {
    return pathname.slice(APP_BASE_PATH.length) || "/";
  }
  return pathname;
}

export function appUrl(path: string): string {
  if (!APP_BASE_PATH || !path.startsWith("/")) return path;
  if (path === APP_BASE_PATH || path.startsWith(`${APP_BASE_PATH}/`)) return path;
  return `${APP_BASE_PATH}${path}`;
}

export function installBasePathAdapters(): void {
  if (!APP_BASE_PATH) return;

  const nativeFetch = window.fetch.bind(window);
  window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (typeof input === "string" && input.startsWith("/")) {
      input = appUrl(input);
    } else if (input instanceof URL && input.pathname.startsWith("/")) {
      input = new URL(appUrl(input.pathname) + input.search, input.origin);
    }
    return nativeFetch(input, init);
  }) as typeof window.fetch;

  const NativeEventSource = window.EventSource;
  window.EventSource = function (url: string | URL, options?: EventSourceInit) {
    return new NativeEventSource(appUrl(url.toString()), options);
  } as unknown as typeof EventSource;
  window.EventSource.prototype = NativeEventSource.prototype;

  document.addEventListener("click", (event) => {
    const target = event.target as Element | null;
    const anchor = target?.closest("a");
    const href = anchor?.getAttribute("href");
    if (!anchor || !href || !href.startsWith("/") || href.startsWith("//") || anchor.target === "_blank") return;
    if (href === APP_BASE_PATH || href.startsWith(`${APP_BASE_PATH}/`)) return;
    event.preventDefault();
    window.location.assign(appUrl(href));
  }, true);

  document.addEventListener("submit", (event) => {
    const form = event.target as HTMLFormElement | null;
    const action = form?.getAttribute("action");
    if (form && action?.startsWith("/") && !action.startsWith(`${APP_BASE_PATH}/`)) {
      form.setAttribute("action", appUrl(action));
    }
  }, true);
}
