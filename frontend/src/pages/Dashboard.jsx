import React from 'react';
import { useNavigate } from 'react-router-dom';

function Dashboard() {
  const navigate = useNavigate();
  const user = JSON.parse(localStorage.getItem('user'));

  const handleLogout = () => {
    localStorage.removeItem('user');
    navigate('/');
  };

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold">Witaj w panelu, {user?.email}</h1>
      <p className="mt-4 text-gray-600">Twój aktualny plan: {user?.current_tariff}</p>
      
      <button 
        onClick={handleLogout}
        className="mt-6 rounded bg-red-500 px-4 py-2 text-white hover:bg-red-600"
      >
        Wyloguj się
      </button>
    </div>
  );
}

export default Dashboard;