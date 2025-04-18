import { useState } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from '/vite.svg'
import './App.css'


import Standings1 from "./components/Sports/Standings/Standings1";
import SideBar from './SideBar';
import HaderReact from './Navbar';


function App() {
  return (
    <div className="min-h-screen bg-gray-100 p-8">
      {/*<SideBar />*/}
      <HaderReact />
      <h1 className="text-2xl font-bold mb-4 text-center text-blue-500 top-0">Classifica</h1>
      <Standings1 />
    </div>
  );
}

export default App
