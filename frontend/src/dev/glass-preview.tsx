// DEV ONLY — entry for /glass-preview.html (see that file). Not in the prod build.
import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import '../styles/tokens.css';
import '../styles/global.css';
import '../styles/glass.css';
import GlassPreview from './GlassPreview';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <GlassPreview />
  </React.StrictMode>,
);
