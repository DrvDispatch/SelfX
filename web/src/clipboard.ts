// Clipboard-image helpers. The DOM `paste` event path works on every origin
// (including a plain-http LAN IP); the async Clipboard API is a secure-context
// enhancement (localhost/https only). See design notes for the full matrix.

const EXT_BY_TYPE: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
  "image/bmp": "bmp",
  "image/avif": "avif",
  "image/tiff": "tif",
};

/** Maximum pasted-image size we accept before nudging the user (aligned with the API upload cap). */
export const MAX_IMAGE_BYTES = 40 * 1024 * 1024;

export function extForType(type: string): string {
  const t = (type || "").split(";")[0].trim().toLowerCase();
  return EXT_BY_TYPE[t] ?? "png";
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** A clean, sortable default name for a pasted screenshot, e.g. screenshot-2026-07-08-142530.png */
export function screenshotName(type = "image/png"): string {
  const d = new Date();
  const ts =
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  return `screenshot-${ts}.${extForType(type)}`;
}

/** Re-wrap a clipboard Blob as a well-named File with a normalized image mime. */
export function blobToNamedFile(blob: Blob, name?: string): File {
  const type = blob.type && blob.type.startsWith("image/") ? blob.type.split(";")[0].trim() : "image/png";
  return new File([blob], name ?? screenshotName(type), { type, lastModified: Date.now() });
}

/** First image File in a paste event's clipboard items, or null (text-only paste). */
export function imageFromPasteEvent(e: ClipboardEvent): File | null {
  const items = e.clipboardData?.items;
  if (!items) return null;
  for (const it of Array.from(items)) {
    if (it.kind === "file" && it.type.startsWith("image/")) {
      const f = it.getAsFile();
      if (f) return blobToNamedFile(f);
    }
  }
  return null;
}

/** True when the async Clipboard read API is actually usable (secure context only). */
export function canReadClipboard(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator.clipboard?.read === "function" &&
    typeof ClipboardItem !== "undefined"
  );
}

/** Async Clipboard API path for a "Paste from clipboard" button. Returns the first image File or null. */
export async function readClipboardImage(): Promise<File | null> {
  if (!canReadClipboard()) return null;
  const items = await navigator.clipboard.read();
  for (const item of items) {
    const type = item.types.find((t) => t.startsWith("image/"));
    if (type) {
      const blob = await item.getType(type);
      return blobToNamedFile(blob);
    }
  }
  return null;
}

/** Ensure a filename ends with a real image extension so tool.accepts matching works. */
export function withImageExt(name: string, type: string): string {
  return /\.[a-z0-9]{2,4}$/i.test(name) ? name : `${name}.${extForType(type)}`;
}
