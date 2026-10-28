# NOC Dashboard — Design Prototype

A standalone static mockup of the "Opsyn Executive Command Centre" view.

**Status:** prototype, not integrated.

- Uses mock data only — makes zero API calls.
- Not referenced by `frontend/vite.config.ts`, so it is not part of the app build.
- Requires `lucide-react`, which is not a dependency of the main frontend.

Kept here rather than in `frontend/src/` so it cannot break `tsc` or the
production build. To work on it, move it into the frontend and add the
dependency listed in this folder's `package.json`.

Originally written 2026-08-21.
