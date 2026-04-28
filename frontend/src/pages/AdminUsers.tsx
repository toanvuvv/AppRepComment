import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { useEffect, useState } from "react";
import {
  AdminUser,
  AdminUserNick,
  AiKeyMode,
  createUser,
  deleteUser,
  listUserNicks,
  listUsers,
  updateUser,
} from "../api/admin";

const REPLY_MODE_COLOR: Record<AdminUserNick["reply_mode"], string> = {
  none: "default",
  knowledge: "purple",
  ai: "geekblue",
  template: "cyan",
};

const MODE_OPTIONS = [
  { value: "system", label: "System (dùng key admin)" },
  { value: "own", label: "Own (tự cấu hình)" },
];

export default function AdminUsersPage() {
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [pwdModal, setPwdModal] = useState<AdminUser | null>(null);
  const [createForm] = Form.useForm();
  const [pwdForm] = Form.useForm();
  const [nicksByUser, setNicksByUser] = useState<Record<number, AdminUserNick[]>>({});
  const [nicksLoading, setNicksLoading] = useState<Record<number, boolean>>({});
  const [expandedKeys, setExpandedKeys] = useState<number[]>([]);

  const loadNicks = async (userId: number) => {
    setNicksLoading((s) => ({ ...s, [userId]: true }));
    try {
      const data = await listUserNicks(userId);
      setNicksByUser((s) => ({ ...s, [userId]: data }));
    } catch {
      message.error("Không tải được danh sách nick");
    } finally {
      setNicksLoading((s) => ({ ...s, [userId]: false }));
    }
  };

  const refresh = async () => {
    setLoading(true);
    try {
      setRows(await listUsers());
      setNicksByUser({});
      setExpandedKeys([]);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async (v: {
    username: string;
    password: string;
    max_nicks?: number;
    ai_key_mode?: AiKeyMode;
  }) => {
    try {
      await createUser({
        username: v.username,
        password: v.password,
        max_nicks: v.max_nicks === undefined ? null : Number(v.max_nicks),
        ai_key_mode: v.ai_key_mode ?? "system",
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

  const handleMode = async (u: AdminUser, mode: AiKeyMode) => {
    try {
      await updateUser(u.id, { ai_key_mode: mode });
      message.success("Đã đổi mode");
      refresh();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail ?? "Không đổi được mode");
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
        scroll={{ x: 1100 }}
        expandable={{
          expandedRowKeys: expandedKeys,
          onExpand: (expanded, record) => {
            const id = record.id;
            setExpandedKeys((keys) =>
              expanded ? [...keys, id] : keys.filter((k) => k !== id)
            );
            if (expanded && nicksByUser[id] === undefined) {
              loadNicks(id);
            }
          },
          rowExpandable: (record) => record.nick_count > 0,
          expandedRowRender: (record) => {
            const data = nicksByUser[record.id] ?? [];
            return (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                loading={nicksLoading[record.id]}
                dataSource={data}
                scroll={{ x: 800 }}
                columns={[
                  { title: "Nick", dataIndex: "name" },
                  { title: "Shopee UID", dataIndex: "shopee_user_id" },
                  {
                    title: "Rep comment",
                    render: (_: unknown, n: AdminUserNick) => (
                      <Tag color={n.reply_enabled ? "green" : "default"}>
                        {n.reply_enabled ? "ON" : "OFF"}
                      </Tag>
                    ),
                  },
                  {
                    title: "Reply mode",
                    dataIndex: "reply_mode",
                    render: (m: AdminUserNick["reply_mode"]) => (
                      <Tag color={REPLY_MODE_COLOR[m]}>{m}</Tag>
                    ),
                  },
                  {
                    title: "Targets",
                    render: (_: unknown, n: AdminUserNick) => (
                      <Space size={4}>
                        {n.reply_to_host && <Tag>host</Tag>}
                        {n.reply_to_moderator && <Tag>moderator</Tag>}
                        {!n.reply_to_host && !n.reply_to_moderator && (
                          <Tag color="default">—</Tag>
                        )}
                      </Space>
                    ),
                  },
                  {
                    title: "Auto-post",
                    dataIndex: "auto_post_enabled",
                    render: (v: boolean) => (
                      <Tag color={v ? "green" : "default"}>{v ? "ON" : "OFF"}</Tag>
                    ),
                  },
                  {
                    title: "Auto-pin",
                    dataIndex: "auto_pin_enabled",
                    render: (v: boolean) => (
                      <Tag color={v ? "green" : "default"}>{v ? "ON" : "OFF"}</Tag>
                    ),
                  },
                ]}
              />
            );
          },
        }}
        columns={[
          { title: "Username", dataIndex: "username" },
          {
            title: "Role",
            dataIndex: "role",
            render: (r: string) => (
              <Tag color={r === "admin" ? "gold" : "blue"}>{r}</Tag>
            ),
          },
          {
            title: "Nicks",
            render: (_: unknown, u: AdminUser) =>
              `${u.nick_count} / ${u.max_nicks ?? "∞"}`,
          },
          {
            title: "Clones",
            dataIndex: "clone_count",
            render: (n: number) => <Tag color="blue">{n}</Tag>,
          },
          {
            title: "Rep ON / Live",
            render: (_: unknown, u: AdminUser) => {
              const on = u.live_reply_enabled_count;
              const total = u.nick_count;
              const color = on === 0 ? "default" : on === total ? "green" : "orange";
              return <Tag color={color}>{on} / {total}</Tag>;
            },
          },
          {
            title: "Max nicks",
            render: (_: unknown, u: AdminUser) => (
              <InputNumber
                min={0}
                value={u.max_nicks ?? undefined}
                placeholder="∞"
                onChange={(v) =>
                  handleQuota(u, v === null || v === undefined ? null : Number(v))
                }
              />
            ),
          },
          {
            title: "AI Key Mode",
            render: (_: unknown, u: AdminUser) => (
              <Select
                style={{ width: "min(200px, 100%)" }}
                value={u.ai_key_mode}
                options={MODE_OPTIONS}
                onChange={(v) => handleMode(u, v as AiKeyMode)}
              />
            ),
          },
          {
            title: "Own key?",
            render: (_: unknown, u: AdminUser) =>
              u.ai_key_mode === "own"
                ? (u.openai_own_key_set ? <Tag color="green">✓</Tag> : <Tag color="red">✗</Tag>)
                : <Tag>—</Tag>,
          },
          {
            title: "Trạng thái",
            render: (_: unknown, u: AdminUser) => (
              <Switch
                checked={!u.is_locked}
                onChange={() => handleToggleLock(u)}
                checkedChildren="Active"
                unCheckedChildren="Locked"
              />
            ),
          },
          {
            title: "Hành động",
            render: (_: unknown, u: AdminUser) => (
              <Space>
                <Button size="small" onClick={() => setPwdModal(u)}>Reset MK</Button>
                <Popconfirm title={`Xóa user ${u.username}?`} onConfirm={() => handleDelete(u)}>
                  <Button size="small" danger>Xóa</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="Tạo user mới"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        width="min(520px, calc(100vw - 16px))"
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{ ai_key_mode: "system" }}
          onFinish={handleCreate}
        >
          <Form.Item
            name="username"
            label="Username"
            rules={[{ required: true, min: 3, max: 50, pattern: /^[A-Za-z0-9_-]+$/, message: "3-50 ký tự, chỉ a-z 0-9 _ -" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label="Mật khẩu"
            rules={[{ required: true, min: 8, message: "Tối thiểu 8 ký tự" }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="max_nicks" label="Giới hạn nick (để trống = không giới hạn)">
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="ai_key_mode" label="AI Key Mode">
            <Select options={MODE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Đặt lại mật khẩu: ${pwdModal?.username ?? ""}`}
        open={!!pwdModal}
        onCancel={() => setPwdModal(null)}
        onOk={() => pwdForm.submit()}
        width="min(520px, calc(100vw - 16px))"
      >
        <Form form={pwdForm} layout="vertical" onFinish={handleReset}>
          <Form.Item name="new_password" label="Mật khẩu mới" rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
