//import { useState } from 'react'
import './App.css'
import { Routes, Route } from "react-router-dom";

import SideBar from './SideBar';
import HaderReact from './Navbar';

import Home from "./pages/home.jsx";
import Standings from "./pages/standings.jsx";


function App() {
  return (
    <div className="min-h-screen bg-gray-100 p-8">
      {/*<SideBar />*/}
      <HaderReact />
      <Routes>
        <Route path="/home" element={<Home />} />
        <Route path="/standings" element={<Standings />} />
      </Routes>
      <h1 className="text-2xl font-bold mb-4 text-center text-blue-500 top-0">Classifica</h1>
    </div>
  );
}

export default App
