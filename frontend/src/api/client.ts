import axios from "axios";

// Đọc API key từ Vite env (VITE_APP_API_KEY trong .env)
// Nếu không có thì để trống — backend sẽ bỏ qua auth khi APP_API_KEY chưa được cấu hình
const API_KEY = import.meta.env.VITE_APP_API_KEY ?? "";

const apiClient = axios.create({
  baseURL: "/api",
  headers: {
    "Content-Type": "application/json",
    ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
  },
});

export default apiClient;
