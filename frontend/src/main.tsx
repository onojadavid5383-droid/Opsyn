// ============================================================
// OPSYN MAIN.TSX — React application entry point
// ============================================================

// Global styles first, in cascade order. tokens.css declares the layers
// (base, glass); component CSS modules are unlayered and always win.
// IBM Plex, self-hosted (Latin subset): bundled with the app, so there is no
// runtime dependency on Google Fonts and nothing for the Docker build to fetch.
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';

import './styles/tokens.css'; /* must precede every other stylesheet */
import './styles/global.css';
import './styles/glass.css';  /* glass material tiers — components/glass */

import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
