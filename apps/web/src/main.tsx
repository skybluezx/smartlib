import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { AppProviders } from './app/AppProviders';
import { router } from './app/router';
import '@carbon/styles/css/styles.css';
import './styles.css';

const root = document.getElementById('root');
if (!root) throw new Error('SmartLib root element is missing');

createRoot(root).render(
  <StrictMode>
    <AppProviders><RouterProvider router={router} /></AppProviders>
  </StrictMode>,
);
