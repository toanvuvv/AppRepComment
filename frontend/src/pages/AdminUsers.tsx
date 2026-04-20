import { Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Space, Switch, Table, Tag, message } from "antd";
import { useEffect, useState } from "react";
import { AdminUser, createUser, deleteUser, listUsers, updateUser } from "../api/admin";

export default function AdminUsersPage() {
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [pwdModal, setPwdModal] = useState<AdminUser | null>(null);
  const [createForm] = Form.useForm();
  const [pwdForm] = Form.useForm();

  const refresh = async () => {
    setLoading(true);
    try { setRows(await listUsers()); }
    finally { setLoading(false); }
  };
  useEffect(() => { refresh(); }, []);

  const handleCreate = async (v: { username: string; password: string; max_nicks?: number }) => {
    try {
      await createUser({
        username: v.username, password: v.password,
        max_nicks: v.max_nicks === undefined ? null : Number(v.max_nicks),
      });
      message.success("Đã tạo user");
      setCreateOpen(false);
      createForm.resetFields();
      refresh();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Tạo user thất bại");
    }
  };

  const handleToggleLock = async (u: AdminUser) => {
    try {
      await updateUser(u.id, { is_locked: !u.is_locked });
      refresh();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Không thể cập nhật");
    }
  };

  const handleQuota = async (u: AdminUser, value: number | null) => {
    try {
      await updateUser(u.id, { max_nicks: value });
      refresh();
    } catch {
      message.error("Không thể cập nhật quota");
    }
  };

  const handleReset = async (v: { new_password: string }) => {
    if (!pwdModal) return;
    try {
      await updateUser(pwdModal.id, { new_password: v.new_password });
      message.success("Đã đặt lại mật khẩu");
      setPwdModal(null);
      pwdForm.resetFields();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Không thể đặt lại");
    }
  };

  const handleDelete = async (u: AdminUser) => {
    try {
      await deleteUser(u.id);
      message.success("Đã xóa");
      refresh();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Xóa thất bại");
    }
  };

  return (
    <Card
      title="Quản lý user"
      extra={<Button type="primary" onClick={() => setCreateOpen(true)}>Tạo user</Button>}
    >
      <Table
        rowKey="id"
        loading={loading}
        dataSource={rows}
        columns={[
          { title: "Username", dataIndex: "username" },
          { title: "Role", dataIndex: "role",
            render: (r: string) => <Tag color={r === "admin" ? "gold" : "blue"}>{r}</Tag> },
          { title: "Nicks", render: (_: unknown, u: AdminUser) => `${u.nick_count} / ${u.max_nicks ?? "∞"}` },
          { title: "Max nicks", render: (_: unknown, u: AdminUser) => (
              <InputNumber min={0} value={u.max_nicks ?? undefined} placeholder="∞"
                onChange={(v) => handleQuota(u, v === null || v === undefined ? null : Number(v))} />
          )},
          { title: "Trạng thái", render: (_: unknown, u: AdminUser) => (
              <Switch checked={!u.is_locked} onChange={() => handleToggleLock(u)}
                      checkedChildren="Active" unCheckedChildren="Locked" />
          )},
          { title: "Hành động", render: (_: unknown, u: AdminUser) => (
              <Space>
                <Button size="small" onClick={() => setPwdModal(u)}>Reset MK</Button>
                <Popconfirm title={`Xóa user ${u.username}?`} onConfirm={() => handleDelete(u)}>
                  <Button size="small" danger>Xóa</Button>
                </Popconfirm>
              </Space>
          )},
        ]}
      />

      <Modal title="Tạo user mới" open={createOpen}
             onCancel={() => setCreateOpen(false)}
             onOk={() => createForm.submit()}>
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="username" label="Username"
                     rules={[{ required: true, min: 3, max: 50,
                               pattern: /^[A-Za-z0-9_-]+$/,
                               message: "3-50 ký tự, chỉ a-z 0-9 _ -" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="Mật khẩu"
                     rules={[{ required: true, min: 8, message: "Tối thiểu 8 ký tự" }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="max_nicks" label="Giới hạn nick (để trống = không giới hạn)">
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`Đặt lại mật khẩu: ${pwdModal?.username ?? ""}`}
             open={!!pwdModal}
             onCancel={() => setPwdModal(null)}
             onOk={() => pwdForm.submit()}>
        <Form form={pwdForm} layout="vertical" onFinish={handleReset}>
          <Form.Item name="new_password" label="Mật khẩu mới"
                     rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
