//import { useState } from 'react'
import './App.css'
import { Routes, Route, Navigate } from "react-router-dom";

//import SideBar from './SideBar';


import Dashboard from "./pages/Dashboard.jsx";
import Standings from "./pages/Standings.jsx";
import Login from "./pages/Login.jsx";
import Welcome from './pages/Welcome.jsx';
import Lineups from "./pages/Lineups.jsx";
//import Register from "./pages/register.jsx";

import { Button } from "flowbite-react";
import DashboardLayout from './layouts/DashboardLayouts.jsx';

function App() {
  const isAuthenticated = true; // 🔥 (dovrai poi cambiarlo dinamicamente)
  return (
    <div className="min-h-screen bg-gray-100 p-8">
      {/*<SideBar />*/}
      <Routes>
        <Route path="/" element={<Welcome />} />
        <Route path="/login" element={<Login />} />

        <Route path="/dashboard" element={isAuthenticated ? <DashboardLayout /> : <Navigate to="/" />}>
          <Route index element={<Dashboard />} /> {/* Rotta di default per /dashboard */}
          <Route path="standings" element={<Standings />} />
          <Route path="lineups" element={<Lineups />} />
        </Route>
      </Routes>
    </div>
  );
}

export default App
