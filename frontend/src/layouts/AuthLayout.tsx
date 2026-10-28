// ============================================================
// OPSYN AUTH LAYOUT — src/layouts/AuthLayout.tsx
// Centred card layout for login/reset pages
// ============================================================

import { Outlet } from 'react-router-dom';

export default function AuthLayout() {
  return (
    <>
      <Outlet />
    </>
  );
}
