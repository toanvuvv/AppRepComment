import { useState } from "react";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import type {
  ProxyCreatePayload,
  ProxyScheme,
  ProxyUpdatePatch,
  SeedingProxy,
} from "../../api/seedingProxy";

const { Text } = Typography;

interface ProxyTableProps {
  proxies: SeedingProxy[];
  loading: boolean;
  onCreate: (payload: ProxyCreatePayload) => Promise<void>;
  onUpdate: (id: number, patch: ProxyUpdatePatch) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

const SCHEME_OPTIONS = [
  { value: "socks5", label: "socks5" },
  { value: "http", label: "http" },
  { value: "https", label: "https" },
];

export function ProxyTable({
  proxies, loading, onCreate, onUpdate, onDelete,
}: ProxyTableProps) {
  const [editing, setEditing] = useState<SeedingProxy | null>(null);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm();

  const openCreate = () => {
    form.resetFields();
    form.setFieldsValue({ scheme: "socks5" });
    setCreating(true);
  };

  const openEdit = (p: SeedingProxy) => {
    form.resetFields();
    form.setFieldsValue({
      scheme: p.scheme, host: p.host, port: p.port,
      username: p.username ?? "", password: "", note: p.note ?? "",
    });
    setEditing(p);
  };

  const onSubmit = async () => {
    try {
      const values = await form.validateFields();
      const payload: ProxyCreatePayload = {
        scheme: values.scheme as ProxyScheme,
        host: values.host.trim(),
        port: Number(values.port),
        username: values.username?.trim() || null,
        password: values.password?.trim() || null,
        note: values.note?.trim() || null,
      };
      if (editing) {
        const patch: ProxyUpdatePatch = { ...payload };
        if (!values.password?.trim()) delete patch.password;
        await onUpdate(editing.id, patch);
        setEditing(null);
      } else {
        await onCreate(payload);
        setCreating(false);
      }
    } catch (e: unknown) {
      if (e instanceof Error) message.error(e.message);
    }
  };

  const columns: ColumnsType<SeedingProxy> = [
    {
      title: "Scheme",
      dataIndex: "scheme",
      width: 90,
      render: (v: ProxyScheme) => <Tag>{v}</Tag>,
    },
    {
      title: "Endpoint",
      key: "endpoint",
      render: (_: unknown, p) => `${p.host}:${p.port}`,
    },
    {
      title: "User",
      dataIndex: "username",
      render: (v: string | null) => v ?? <Text type="secondary">—</Text>,
    },
    {
      title: "Note",
      dataIndex: "note",
      render: (v: string | null) => v ?? <Text type="secondary">—</Text>,
    },
    {
      title: "Đang dùng",
      dataIndex: "used_by_count",
      width: 100,
      render: (n: number) => <Tag color={n > 0 ? "blue" : "default"}>{n} clone</Tag>,
    },
    {
      title: "",
      key: "actions",
      width: 100,
      render: (_: unknown, p) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(p)}
          />
          <Popconfirm
            title={
              p.used_by_count > 0
                ? `${p.used_by_count} clone đang dùng proxy này. Xoá?`
                : "Xoá proxy này?"
            }
            okText="Xoá"
            cancelText="Huỷ"
            onConfirm={() => onDelete(p.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Space style={{ justifyContent: "space-between", width: "100%" }}>
        <Text strong>Danh sách proxy ({proxies.length})</Text>
        <Button icon={<PlusOutlined />} onClick={openCreate}>
          Thêm thủ công
        </Button>
      </Space>
      <Table<SeedingProxy>
        rowKey="id"
        columns={columns}
        dataSource={proxies}
        loading={loading}
        size="small"
        pagination={false}
      />
      <Modal
        open={creating || editing !== null}
        title={editing ? "Sửa proxy" : "Thêm proxy"}
        onOk={onSubmit}
        onCancel={() => { setCreating(false); setEditing(null); }}
        okText="Lưu"
        cancelText="Huỷ"
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="scheme" label="Scheme"
            rules={[{ required: true }]}
          >
            <Select options={SCHEME_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="host" label="Host"
            rules={[{ required: true, message: "Host bắt buộc" }]}
          >
            <Input placeholder="proxyx3.ddns.net" />
          </Form.Item>
          <Form.Item
            name="port" label="Port"
            rules={[
              { required: true, message: "Port bắt buộc" },
              { type: "number", min: 1, max: 65535, message: "Port không hợp lệ" },
            ]}
          >
            <InputNumber min={1} max={65535} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="username" label="Username">
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label={editing ? "Password (để trống = giữ nguyên)" : "Password"}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="note" label="Ghi chú">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
