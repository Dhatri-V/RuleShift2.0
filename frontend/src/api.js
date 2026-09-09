export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export const ADMIN_TOKEN_KEY = "ruleshift_admin_token";


export async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, options);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Something went wrong.");
  }

  return data;
}


export function getStoredAdminToken() {
  try {
    return localStorage.getItem(ADMIN_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}


export function storeAdminToken(token) {
  try {
    localStorage.setItem(ADMIN_TOKEN_KEY, token);
  } catch {
    // localStorage unavailable; admin session stays in memory only.
  }
}


export function clearAdminToken() {
  try {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    // Nothing to clean up.
  }
}


export function adminHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}