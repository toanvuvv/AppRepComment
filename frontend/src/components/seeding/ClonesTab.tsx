import { useState } from "react";
import {
  Button,
  Input,
  Space,
  Table,
  Tag,
  Typography,
  Popconfirm,
  message,
  Alert,
} from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useSeedingClones } from "../../hooks/useSeedingClones";
import type { SeedingClone } from "../../api/seeding";
import { ProxySettingsModal } from "./ProxySettingsModal";

const { Title, Text } = Typography;
const { TextArea } = Input;

function getErrorDetail(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Lỗi không xác định";
}

export function ClonesTab() {
  const { clones, loading, error, refresh, create, remove } =
    useSeedingClones();

  const [jsonText, setJsonText] = useState("");
  const [adding, setAdding] = useState(false);
  const [proxyModalOpen, setProxyModalOpen] = useState(false);

  const onAdd = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      message.error("JSON không hợp lệ");
      return;
    }
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      message.error("JSON phải là một object");
      return;
    }
    setAdding(true);
    try {
      await create(parsed as Parameters<typeof create>[0]);
      message.success("Thêm clone thành công");
      setJsonText("");
    } catch (e: unknown) {
      message.error("Tạo clone thất bại: " + getErrorDetail(e));
    } finally {
      setAdding(false);
    }
  };

  const columns: ColumnsType<SeedingClone> = [
    { title: "Tên", dataIndex: "name", key: "name" },
    { title: "Shopee ID", dataIndex: "shopee_user_id", key: "shopee_user_id" },
    {
      title: "Proxy",
      key: "proxy",
      render: (_: unknown, record) =>
        record.proxy_meta ? (
          <Space size={4}>
            <Tag>{record.proxy_meta.scheme}</Tag>
            <Text>
              {record.proxy_meta.host}:{record.proxy_meta.port}
            </Text>
          </Space>
        ) : (
          <Text type="secondary">— chưa gán —</Text>
        ),
    },
    {
      title: "Last sent",
      dataIndex: "last_sent_at",
      key: "last_sent_at",
      render: (v: string | null) => <Text type="secondary">{v ?? "-"}</Text>,
    },
    {
      title: "",
      key: "actions",
      width: 80,
      render: (_: unknown, record) => (
        <Popconfirm
          title="Xoá clone này?"
          onConfirm={() =>
            remove(record.id).catch((e: unknown) =>
              message.error("Xoá thất bại: " + getErrorDetail(e)),
            )
          }
          okText="Xoá"
          cancelText="Huỷ"
        >
          <Button danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="large">
      <Space style={{ justifyContent: "space-between", width: "100%" }}>
        <Title level={4} style={{ marginBottom: 0 }}>Clone pool</Title>
        <Button
          icon={<SettingOutlined />}
          onClick={() => setProxyModalOpen(true)}
        >
          Setting Proxy
        </Button>
      </Space>

      {error && <Alert type="error" message={error} showIcon closable />}

      <Table<SeedingClone>
        dataSource={clones}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
      />

      <div>
        <Title level={5}>Thêm clone (JSON giống NickLive)</Title>
        <Space direction="vertical" style={{ width: "100%" }}>
          <TextArea
            rows={6}
            value={jsonText}
            placeholder={
              '{\n  "name": "Clone 1",\n  "shopee_user_id": "12345",\n  "cookies": "SPC_EC=..."\n}'
            }
            onChange={(e) => setJsonText(e.target.value)}
            style={{ fontFamily: "monospace" }}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={onAdd}
            loading={adding}
            disabled={!jsonText.trim()}
          >
            Thêm Clone
          </Button>
        </Space>
      </div>

      <ProxySettingsModal
        open={proxyModalOpen}
        onClose={() => setProxyModalOpen(false)}
        cloneCount={clones.length}
        onAfterAssign={refresh}
      />
    </Space>
  );
}
