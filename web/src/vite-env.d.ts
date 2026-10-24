/// <reference types="vite/client" />

/** True in `npm run dev:mock` (VITE_MOCK=1). Replaced at build time, so mock code is tree-shaken otherwise. */
declare const __MOCK__: boolean;
