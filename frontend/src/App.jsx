import { BrowserRouter, Routes, Route } from "react-router-dom";
import { GoogleOAuthProvider } from "@react-oauth/google";
import Login from "./pages/Login";
import "./index.css";

function App() {
  // Prawdziwy klucz wygenerowany z Google Cloud Console
  const GOOGLE_CLIENT_ID =
    "13518631048-hm0jlnrgj7utm440e63ri5oi93s5pfu3.apps.googleusercontent.com";

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Login />} />
        </Routes>
      </BrowserRouter>
    </GoogleOAuthProvider>
  );
}

export default App;
