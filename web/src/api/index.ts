import type { Api } from './client';
import { createHttpApi } from './http';

export type { Api, TaskEvent, TaskKind } from './client';
export * from './errors';
export type * from './types';

/** The active API. Assigned once by initApi() before the app renders (ES modules keep this binding live). */
export let api: Api = createHttpApi();

export async function initApi(): Promise<void> {
  if (__MOCK__) {
    // Only reachable in `npm run dev:mock`; the production build replaces __MOCK__ with false and drops this chunk.
    const { createMockApi } = await import('../mocks/mockApi');
    api = createMockApi();
  }
}
