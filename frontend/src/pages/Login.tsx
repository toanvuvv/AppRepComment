import { Form, Input, Button, Alert, Typography } from "antd";
import { UserOutlined, LockOutlined, CommentOutlined, ThunderboltOutlined, RobotOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useNavigate, useLocation, Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { login as loginApi } from "../api/auth";

const { Title, Paragraph, Text } = Typography;

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
    <div className="login-page">
      <div className="login-shell">
        <div className="login-hero">
          <img src="/Logo.png" alt="Logo" className="login-hero-logo" />
          <Title level={2} style={{ color: "#fff", marginBottom: 8 }}>
            Trợ lý Quản lý Comment
          </Title>
          <Paragraph style={{ color: "rgba(255,255,255,0.85)", fontSize: 15, marginBottom: 28 }}>
            Nền tảng hỗ trợ quét, phân tích và phản hồi bình luận trên các sàn TMĐT
            kết hợp AI — giúp bạn chăm sóc khách hàng nhanh và chuyên nghiệp hơn.
          </Paragraph>

          <div className="login-feature">
            <CommentOutlined className="login-feature-icon" />
            <div>
              <Text strong style={{ color: "#fff" }}>Quét comment thời gian thực</Text>
              <div style={{ color: "rgba(255,255,255,0.75)", fontSize: 13 }}>
                Theo dõi và quản lý bình luận từ nhiều shop cùng lúc.
              </div>
            </div>
          </div>
          <div className="login-feature">
            <RobotOutlined className="login-feature-icon" />
            <div>
              <Text strong style={{ color: "#fff" }}>Trả lời tự động bằng AI</Text>
              <div style={{ color: "rgba(255,255,255,0.75)", fontSize: 13 }}>
                Sinh nội dung phản hồi sát ngữ cảnh sản phẩm và shop.
              </div>
            </div>
          </div>
          <div className="login-feature">
            <ThunderboltOutlined className="login-feature-icon" />
            <div>
              <Text strong style={{ color: "#fff" }}>Seeding & chăm sóc đơn hàng</Text>
              <div style={{ color: "rgba(255,255,255,0.75)", fontSize: 13 }}>
                Tăng tương tác và độ tin cậy cho gian hàng.
              </div>
            </div>
          </div>
        </div>

        <div className="login-form-wrap">
          <div className="login-form-card">
            <div className="login-form-head">
              <img src="/Logo.png" alt="Logo" className="login-form-logo" />
              <Title level={3} style={{ marginBottom: 4 }}>Đăng nhập</Title>
              <Text type="secondary">Chào mừng bạn quay lại 👋</Text>
            </div>

            {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} showIcon />}

            <Form layout="vertical" onFinish={onFinish} disabled={loading} size="large">
              <Form.Item
                label="Tên đăng nhập"
                name="username"
                rules={[{ required: true, message: "Bắt buộc" }]}
              >
                <Input prefix={<UserOutlined />} autoFocus placeholder="Nhập tên đăng nhập" />
              </Form.Item>
              <Form.Item
                label="Mật khẩu"
                name="password"
                rules={[{ required: true, message: "Bắt buộc" }]}
              >
                <Input.Password prefix={<LockOutlined />} placeholder="Nhập mật khẩu" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block loading={loading} size="large">
                Đăng nhập
              </Button>
            </Form>

            <div className="login-foot">
              <Text type="secondary" style={{ fontSize: 12 }}>
                &copy; {new Date().getFullYear()} App Rep Comment
              </Text>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
