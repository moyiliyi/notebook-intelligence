// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>
//
// Pure helpers and event constants used by the notebook-generation toolbar
// button. Keeping these in their own module (free of JupyterLab/React
// dependencies) makes them easy to unit-test under jsdom without bringing
// in the chat sidebar's heavyweight ESM imports.

export const NOTEBOOK_GENERATION_PROMPT_PREFIX =
  "Update active notebook based on the user request. Don't create a new notebook, always update the active one. User request: ";

export const NOTEBOOK_GENERATION_PROGRESS_EVENT =
  'copilotSidebar:notebookGenerationProgress';

export interface INotebookGenerationProgressDetail {
  requestId: string;
  inProgress: boolean;
  error?: string;
}

export function buildNotebookGenerationPrompt(rawPrompt: string): string {
  const trimmed = (rawPrompt || '').trim();
  return `${NOTEBOOK_GENERATION_PROMPT_PREFIX}${trimmed}`;
}
