import {
  Boxes,
  Captions,
  Clapperboard,
  FileText,
  FileType2,
  Image as ImageIcon,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface CategoryMeta {
  key: string;
  label: string;
  icon: LucideIcon;
  /** CSS color token name (see index.css @theme), used as var(--color-<accent>) */
  accent: string;
  blurb: string;
}

export const CATEGORIES: Record<string, CategoryMeta> = {
  pdf: { key: "pdf", label: "PDF", icon: FileText, accent: "pdf", blurb: "Merge, convert, protect & edit PDFs" },
  documents: { key: "documents", label: "Documents", icon: FileType2, accent: "docs", blurb: "Office, ebooks, OCR & Markdown" },
  images: { key: "images", label: "Images", icon: ImageIcon, accent: "img", blurb: "Convert, resize, remove background & caption" },
  media: { key: "media", label: "Media", icon: Clapperboard, accent: "media", blurb: "Audio & video convert, denoise, download" },
  subtitles: { key: "subtitles", label: "Subtitles", icon: Captions, accent: "subs", blurb: "Convert, extract & sync subtitles" },
  ai: { key: "ai", label: "AI", icon: Sparkles, accent: "ai", blurb: "Summarize, transcribe & chat with documents" },
  utilities: { key: "utilities", label: "Utilities", icon: Wrench, accent: "util", blurb: "QR, barcode, hashes, metadata & virus scan" },
};

export const CATEGORY_ORDER = ["pdf", "documents", "images", "media", "subtitles", "ai", "utilities"];

export function categoryMeta(key: string): CategoryMeta {
  return (
    CATEGORIES[key] ?? { key, label: key, icon: Boxes, accent: "quick", blurb: "" }
  );
}

/** var(--color-<accent>) helper for inline styles. */
export function accentVar(accent: string): string {
  return `var(--color-${accent})`;
}
