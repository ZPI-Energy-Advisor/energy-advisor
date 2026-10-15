// Pomocnicze funkcje do testów: sztuczny JWT i zalogowany użytkownik w localStorage.

export const fakeJwt = (payload) => {
  const encode = (value) =>
    btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode(payload)}.signature`;
};

export const loginAs = ({ id = "user-1", email = "jan@example.com" } = {}) => {
  localStorage.setItem("access_token", fakeJwt({ sub: id, type: "access" }));
  localStorage.setItem("refresh_token", fakeJwt({ sub: id, type: "refresh" }));
  localStorage.setItem("user", JSON.stringify({ id, email }));
};
