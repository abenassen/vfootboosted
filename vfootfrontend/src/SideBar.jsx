import { FaFire, FaPoo } from "react-icons/fa";
import { BsPlus } from "react-icons/bs";


const SideBar = () => {
    return (
        <div className="fixed top-0 left-0 h-screen w-16 bg-custom-gray-700 text-white flex flex-col items-center py-4 shadow-lg">
            <SideBarIcon icon={<BsPlus size="18" />} text="Plus" />
            <SideBarIcon icon={<FaFire size="18" />} text="Fire" />
            <SideBarIcon icon={<FaPoo size="18" />} text="Poo" />
        </div>
    );
    }   

const SideBarIcon = ({ icon, text }) => {
    return (
        <div className=" text-custom-green-500 sidebar-icon group mt-2 mb-2 h-12 w-12 flex flex-col items-center justify-center bg-custom-gray-600 cursor-pointer rounded-xl hover:rounded-3xl transition-all relative">
            {icon}
            <span className="sidebar-tooltip group-hover:scale-100">
                {text}
            </span>
        </div>
    );
}

export default SideBar;