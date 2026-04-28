import { Form, Input, Button, Card, message } from "antd";
import { useState } from "react";
import { changePassword } from "../api/auth";

export default function ChangePasswordPage() {
  const [loading, setLoading] = useState(false);

  const onFinish = async (v: { old: string; next: string; confirm: string }) => {
    if (v.next !== v.confirm) {
      message.error("Mật khẩu xác nhận không khớp");
      return;
    }
    setLoading(true);
    try {
      await changePassword(v.old, v.next);
      message.success("Đổi mật khẩu thành công");
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Đổi mật khẩu thất bại");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app-page">
      <Card title="Đổi mật khẩu" style={{ maxWidth: 480, width: "100%", margin: "24px auto" }}>
        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item label="Mật khẩu hiện tại" name="old" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item label="Mật khẩu mới" name="next"
                     rules={[{ required: true, min: 8, message: "Tối thiểu 8 ký tự" }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item label="Xác nhận mật khẩu mới" name="confirm"
                     rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>Lưu</Button>
        </Form>
      </Card>
    </div>
  );
}
