import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles/index.css';
import { AuthProvider } from './auth/AuthContext';
import { registerServiceWorker } from './pwa/registerSW';
import { watchInstallPrompt } from './pwa/install';

// Before the first render, so Android's install prompt is captured rather than
// shown by the browser at a moment of its own choosing.
watchInstallPrompt();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>
);

// After render, never before: the service worker is an enhancement and must not
// sit on the critical path to the first screen.
void registerServiceWorker();
