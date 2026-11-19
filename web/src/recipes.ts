import type { WorkflowAction, WorkflowPlan } from "./api";

export interface Recipe {
  id: string;
  name: string;
  description?: string;
  plan: WorkflowPlan;
}

type PortableRecipe = Omit<Recipe, "id"> & { format: "selfx-recipe"; version: 1 };
export const RECIPE_FILE_LIMIT = 64 * 1024;
export const RECIPE_CHANGED = "selfx:recipes-changed";
const MAX_RECIPES = 40;
const ID = /^[a-z][a-z0-9_-]{0,31}$/;
const KEY = /^[a-z][a-z0-9_]{0,31}$/;
const PRIVATE_FIELD = /password|token|secret|api_?key|file_?(id|name)|prompt|(?:^|_)path(?:$|_)/;

export const STARTER_RECIPES: Recipe[] = [
  {
    id: "creator-captions",
    name: "Creator captions",
    description: "Turn a recording into a timestamped transcript with SRT and WebVTT captions.",
    plan: { steps: [
      { id: "recording", action: "transcript-pdf", input: "source", params: { language: "auto" } },
      { id: "web-captions", action: "subtitle-convert", input: "recording.captions", params: { to: "vtt" } },
    ] },
  },
  {
    id: "searchable-scan",
    name: "Searchable scan",
    description: "Recognize text in an English PDF scan and keep a searchable PDF and a text copy.",
    plan: { steps: [
      { id: "search", action: "ocr-pdf", input: "source", params: { language: "eng", deskew: true } },
      { id: "text", action: "pdf-extract-text", input: "search.pdf", params: {} },
    ] },
  },
  {
    id: "web-image",
    name: "Web-ready image",
    description: "Resize an image to fit within 1600 px and export as WebP.",
    plan: { steps: [
      { id: "web", action: "image-convert", input: "source", params: { format: "webp", max_width: 1600, max_height: 1600, quality: 82 } },
    ] },
  },
  {
    id: "pdf-handoff",
    name: "PDF handoff",
    description: "Compress a PDF for sharing and include its text as a separate file.",
    plan: { steps: [
      { id: "share", action: "pdf-compress", input: "source", params: { quality: "ebook", fast_web_view: true } },
      { id: "text", action: "pdf-extract-text", input: "share.pdf", params: {} },
    ] },
  },
  {
    id: "video-attachment",
    name: "Video under 25 MB",
    description: "Encode an MP4 with a 25 MB file size limit for sharing or uploading.",
    plan: { steps: [
      { id: "attachment", action: "video-target-size", input: "source", params: { target_mb: 25 } },
    ] },
  },
  {
    id: "pdf-cover",
    name: "PDF first-page preview",
    description: "Keep the first page as a separate PDF and extract its text for a quick preview.",
    plan: { steps: [
      { id: "cover", action: "pdf-organize", input: "source", params: { page_order: "1" } },
      { id: "text", action: "pdf-extract-text", input: "cover.pdf", params: {} },
    ] },
  },
];

export function recipeKey(userId: string): string {
  return `selfx.recipes.v1.${userId}`;
}

export function newRecipeId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("");
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function scalar(value: unknown): value is boolean | number | string {
  return typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))
    || (typeof value === "string" && value.length <= 400);
}

function readPlan(value: unknown): WorkflowPlan {
  if (!record(value) || Object.keys(value).length !== 1 || !Array.isArray(value.steps)
      || value.steps.length < 1 || value.steps.length > 6) {
    throw new Error("A recipe needs one to six steps.");
  }
  const previous = new Set<string>();
  const steps = value.steps.map((step: unknown) => {
    if (!record(step) || Object.keys(step).length !== 4 || typeof step.id !== "string" || !ID.test(step.id)
        || previous.has(step.id) || typeof step.action !== "string" || !ID.test(step.action)
        || typeof step.input !== "string" || !record(step.params)) {
      throw new Error("A recipe step has an invalid name, action, input or settings.");
    }
    const [parent, role, extra] = step.input.split(".");
    if (step.input !== "source" && (!previous.has(parent) || !role || !ID.test(role) || extra !== undefined)) {
      throw new Error("Every step must use the new file or an earlier step’s result.");
    }
    const settings = Object.entries(step.params);
    if (settings.length > 20 || settings.some(([key, parameter]) => !KEY.test(key) || PRIVATE_FIELD.test(key) || !scalar(parameter))) {
      throw new Error("A recipe can only include portable action settings.");
    }
    previous.add(step.id);
    return {
      id: step.id, action: step.action, input: step.input,
      params: Object.fromEntries(settings.filter(([key]) => key !== "title")),
    };
  });
  return { steps };
}

function readRecipe(value: unknown): PortableRecipe {
  if (!record(value) || value.format !== "selfx-recipe" || value.version !== 1
      || Object.keys(value).some((key) => !["format", "version", "name", "description", "plan"].includes(key))) {
    throw new Error("Choose a SelfX recipe file in version 1 format.");
  }
  const name = typeof value.name === "string" ? value.name.trim() : "";
  const description = typeof value.description === "string" ? value.description.trim() : undefined;
  if (!name || name.length > 64 || (description && description.length > 180)) {
    throw new Error("A recipe needs a name of up to 64 characters and a short description.");
  }
  return { format: "selfx-recipe", version: 1, name, description, plan: readPlan(value.plan) };
}

function portable(recipe: Omit<Recipe, "id">): PortableRecipe {
  return readRecipe({ format: "selfx-recipe", version: 1, name: recipe.name, description: recipe.description, plan: recipe.plan });
}

function matchesParameter(value: unknown, parameter: WorkflowAction["params_schema"]["properties"][string]): boolean {
  if (parameter.enum && !parameter.enum.includes(value)) return false;
  if (typeof value === "string") {
    return parameter.type === "string" && value.length <= (parameter.maxLength ?? 400)
      && (!parameter.pattern || new RegExp(parameter.pattern).test(value));
  }
  if (typeof value === "boolean") return parameter.type === "boolean";
  if (typeof value === "number") {
    return (parameter.type === "number" || (parameter.type === "integer" && Number.isInteger(value)))
      && value >= (parameter.minimum ?? -Infinity) && value <= (parameter.maximum ?? Infinity);
  }
  return false;
}

export function checkRecipe(plan: WorkflowPlan, catalog: WorkflowAction[]): { extensions: string[]; reason?: string } {
  const actions = new Map(catalog.map((action) => [action.slug, action]));
  for (const step of plan.steps) {
    const action = actions.get(step.action);
    if (!action) return { extensions: [], reason: "An action in this recipe is unavailable on this server." };
    const properties = action.params_schema.properties;
    const supplied = Object.entries(step.params);
    if (supplied.some(([key, value]) => PRIVATE_FIELD.test(key) || !Object.hasOwn(properties, key) || !matchesParameter(value, properties[key]))
        || action.params_schema.required.some((key) => !Object.hasOwn(step.params, key) && properties[key]?.default === undefined)) {
      return { extensions: [], reason: "An action setting is unsupported on this server." };
    }
  }

  const first = actions.get(plan.steps[0].action);
  const extensions = (first?.input_extensions ?? []).filter((extension) => {
    const files = new Map([["source", extension]]);
    return plan.steps.every((step) => {
      const action = actions.get(step.action)!;
      const input = files.get(step.input);
      if (!input || !action.input_extensions.includes(input)) return false;
      for (const output of action.outputs) {
        const setting = output.format_parameter;
        const format = setting
          ? `.${String(step.params[setting] ?? action.params_schema.properties[setting]?.default)}`
          : output.extensions.length === 1 ? output.extensions[0] : input;
        if (!output.extensions.includes(format)) return false;
        files.set(`${step.id}.${output.role}`, format);
      }
      return true;
    });
  });
  return extensions.length > 0 ? { extensions } : { extensions, reason: "These steps do not have compatible file types." };
}

export function readSavedRecipes(userId: string): Recipe[] {
  try {
    const list: unknown = JSON.parse(localStorage.getItem(recipeKey(userId)) ?? "[]");
    if (!Array.isArray(list)) return [];
    return list.slice(0, MAX_RECIPES).flatMap((item: unknown) => {
      if (!record(item) || typeof item.id !== "string" || !/^[a-f0-9]{32}$/.test(item.id)) return [];
      try {
        const recipe = readRecipe(item.recipe);
        return [{ id: item.id, name: recipe.name, description: recipe.description, plan: recipe.plan }];
      } catch {
        return [];
      }
    });
  } catch {
    return [];
  }
}

function writeSavedRecipes(userId: string, recipes: Recipe[]) {
  localStorage.setItem(recipeKey(userId), JSON.stringify(
    recipes.map((recipe) => ({ id: recipe.id, recipe: portable(recipe) })),
  ));
  window.dispatchEvent(new Event(RECIPE_CHANGED));
}

export function saveRecipe(userId: string, draft: Omit<Recipe, "id">, catalog: WorkflowAction[]): Recipe {
  const { name, description, plan } = portable(draft);
  const existing = readSavedRecipes(userId);
  if (existing.length >= MAX_RECIPES) throw new Error("Remove a saved recipe before adding another.");
  if (existing.some((item) => item.name.toLowerCase() === name.toLowerCase())) {
    throw new Error("You already have a recipe with this name.");
  }
  const { reason } = checkRecipe(plan, catalog);
  if (reason) throw new Error(reason);
  const recipe = { id: newRecipeId(), name, description, plan };
  writeSavedRecipes(userId, [recipe, ...existing]);
  return recipe;
}

export function importRecipe(userId: string, source: string, catalog: WorkflowAction[]): Recipe {
  let value: unknown;
  try {
    value = JSON.parse(source);
  } catch {
    throw new Error("This file does not contain valid JSON.");
  }
  return saveRecipe(userId, readRecipe(value), catalog);
}

export function deleteRecipe(userId: string, id: string) {
  writeSavedRecipes(userId, readSavedRecipes(userId).filter((recipe) => recipe.id !== id));
}

export function renameRecipe(userId: string, id: string, name: string): Recipe {
  const recipes = readSavedRecipes(userId);
  const item = recipes.find((recipe) => recipe.id === id);
  if (!item) throw new Error("This recipe is no longer saved.");
  const named = { ...item, name: portable({ ...item, name }).name };
  if (recipes.some((recipe) => recipe.id !== id && recipe.name.toLowerCase() === named.name.toLowerCase())) {
    throw new Error("You already have a recipe with this name.");
  }
  writeSavedRecipes(userId, recipes.map((recipe) => recipe.id === id ? named : recipe));
  return named;
}

export function exportRecipe(recipe: Recipe) {
  const content = JSON.stringify(portable(recipe), null, 2);
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${recipe.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "recipe"}.selfx.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
