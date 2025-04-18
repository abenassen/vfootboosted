Crea un progetto:


npm create vite@latest nome-progetto -- --template react
cd nome-progetto
npm install


Installa plugin tailwind per vite
npm install tailwindcss @tailwindcss/vite


Configura vite.config.js
Apri il file vite.config.js e modificalo così:

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
})


Crea il file src/styles.css e scrivici dentro:
@import "tailwindcss";


Importa il CSS nel tuo main.jsx

import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './styles.css'  // importa qui!

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)



Avvia il server
npm run dev


Plugin supplementari:
npm install @heroicons/react

Nota che nelle versioni di tailwind <4, si usava un file di configurazione per personalizzare il tema nella folder root: tailwind.config.js. A partire dalla 4, in teoria le personalizzazioni del tema vengono effettuate dal file styles.css all'interno della cartella src. E' possibile usare comunque il file di configurazione js, aggiungendo la riga 

@config "./tailwind.config.js";

all'inizio del file styles.css
