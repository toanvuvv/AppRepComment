import { Form, Input, Button, Card, Alert } from "antd";
import { useState } from "react";
import { useNavigate, useLocation, Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { login as loginApi } from "../api/auth";

export default function LoginPage() {
  const { token, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (token) {
    return <Navigate to="/" replace />;
  }

  const onFinish = async (values: { username: string; password: string }) => {
    setError(null);
    setLoading(true);
    try {
      const res = await loginApi(values.username, values.password);
      login(res.access_token, res.user);
      const to = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(to, { replace: true });
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 429) {
        setError("Quá nhiều lần thử. Vui lòng đợi 15 phút.");
      } else if (err.response?.status === 403) {
        setError("Tài khoản đã bị khóa");
      } else if (err.response?.status === 401) {
        setError("Sai tài khoản hoặc mật khẩu");
      } else {
        setError(err.response?.data?.detail ?? "Đăng nhập thất bại");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center",
                  minHeight: "100vh", background: "#f0f2f5", padding: 12 }}>
      <Card title="Đăng nhập" style={{ width: "min(380px, calc(100vw - 24px))" }}>
        {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
        <Form layout="vertical" onFinish={onFinish} disabled={loading}>
          <Form.Item label="Tên đăng nhập" name="username"
                     rules={[{ required: true, message: "Bắt buộc" }]}>
            <Input autoFocus />
          </Form.Item>
          <Form.Item label="Mật khẩu" name="password"
                     rules={[{ required: true, message: "Bắt buộc" }]}>
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            Đăng nhập
          </Button>
        </Form>
      </Card>
    </div>
  );
}
