import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/globals.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <div className="container py-8">
      <h1 className="text-3xl font-semibold">YAS</h1>
      <p className="text-muted-foreground">Tailwind base wired.</p>
    </div>
  </StrictMode>,
);
