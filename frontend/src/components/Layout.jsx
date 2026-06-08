import React from 'react';
import { Link, useLocation, Outlet, useNavigate } from 'react-router-dom';
import { FiHome, FiUploadCloud, FiPieChart, FiLogOut } from 'react-icons/fi';

function Layout() {
  const location = useLocation();
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem('user');
    navigate('/');
  };

  const isActive = (path) => location.pathname === path;

  const navItems = [
    { path: '/dashboard', label: 'Dashboard', icon: <FiHome className="mr-3 text-lg" /> },
    { path: '/upload', label: 'Import Danych', icon: <FiUploadCloud className="mr-3 text-lg" /> },
    { path: '/results', label: 'Analiza Taryf', icon: <FiPieChart className="mr-3 text-lg" /> },
  ];

  return (
    <div className="flex h-screen bg-gray-50 font-sans text-gray-900 overflow-hidden">
      <div className="w-64 bg-white border-r border-gray-200 flex flex-col shadow-sm z-10 h-full">
        <div className="p-6">
          <h1 className="text-2xl font-bold tracking-tight">
            Energy<span className="text-emerald-500">Advisor</span>
          </h1>
        </div>
        
        <nav className="flex-1 mt-6">
          {navItems.map((item) => (
            <Link 
              key={item.path}
              to={item.path} 
              className={`flex items-center px-6 py-4 text-sm font-medium transition-colors ${
                isActive(item.path) 
                  ? 'bg-emerald-50 border-l-4 border-emerald-500 text-emerald-700' 
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900 border-l-4 border-transparent'
              }`}
            >
              {item.icon}
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="p-4 border-t border-gray-200">
          <button 
            onClick={handleLogout}
            className="flex items-center w-full px-4 py-3 text-sm font-medium text-red-600 hover:bg-red-50 rounded transition-colors"
          >
            <FiLogOut className="mr-3 text-lg" />
            Wyloguj się
          </button>
        </div>
      </div>

      <div className="flex-1 p-10 overflow-y-auto h-full">
        <Outlet /> 
      </div>
    </div>
  );
}

export default Layout;