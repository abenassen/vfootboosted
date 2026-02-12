import { Link } from "react-router-dom";
import { useState } from "react";
import CarouselWithImages from "../components/Carousel";

import logobig from "@assets/logobig.png"; 

function LogoBig() {
  return (
    <img
      src={logobig} 
      alt="Logo"
      className="h-60 w-aut" // oppure dimensioni a tua scelta
    />
  );
}


export default function Welcome() {
  const [activeItemIndex, setActiveItemIndex] = useState(0);
  return (
    <div>
      <div className="flex flex-col items-center justify-center min-h-50 bg-gray-100">
        <h1 className="text-4xl font-bold mb-8">Benvenuto su VFoot!</h1>
        <div className="flex gap-4">
          <Link to="/login" className="px-6 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">
            Login
          </Link>
          <Link to="/register" className="px-6 py-2 bg-green-500 text-white rounded hover:bg-green-600">
            Registrati
          </Link>
        </div>
      </div>
      <div className="flex place-items-center justify-center">
            <LogoBig />
      </div>
      <div className="grid place-items-center">
        <CarouselWithImages
          activeItemIndex={activeItemIndex}
          setActiveItemIndex={setActiveItemIndex}
        />
      </div>
    </div>
  );
}
