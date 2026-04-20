import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Modal,
  Tabs,
  Button,
  Input,
  InputNumber,
  List,
  Switch,
  Select,
  Space,
  Table,
  Popconfirm,
  Typography,
  Tag,
  Divider,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  PlusOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  ThunderboltOutlined,
  DatabaseOutlined,
} from "@ant-design/icons";

import {
  getHostStatus,
  getHostCredentials,
  getAutoPostTemplates,
  createAutoPostTemplate,
  updateAutoPostTemplate,
  deleteAutoPostTemplate,
  startAutoPost,
  stopAutoPost,
  getAutoPostStatus,
  getReplyTemplates,
  createReplyTemplate,
  deleteReplyTemplate,
  getNickSettings,
  updateNickSettings,
  type HostConfigStatus,
  type AutoPostTemplate,
  type ReplyTemplate,
  type NickLiveSettings,
  type NickLiveSettingsUpdate,
  type ReplyMode,
} from "../api/hostConfig";

import {
  getModeratorStatus,
  saveModeratorCurl,
  type ModeratorStatus,
} from "../api/nickLive";

import {
  getKnowledgeProducts,
  parseKnowledgeProducts,
  deleteKnowledgeProducts,
  type KnowledgeProduct,
} from "../api/knowledge";

const { TextArea } = Input;
const { Text, Title } = Typography;

interface Props {
  nickLiveId: number;
  nickName: string;
  sessionId: number | null;
  open: boolean;
  onClose: () => void;
}

export default function NickConfigModal({
  nickLiveId,
  nickName,
  sessionId,
  open,
  onClose,
}: Props) {
  // --- Host Config state ---
  const [proxy, setProxy] = useState("");
  const [hostStatus, setHostStatus] = useState<HostConfigStatus | null>(null);
  const [hostLoading, setHostLoading] = useState(false);

  // --- Auto-post state ---
  const [autoPostTemplates, setAutoPostTemplates] = useState<AutoPostTemplate[]>([]);
  const [newPostContent, setNewPostContent] = useState("");
  const [newPostMin, setNewPostMin] = useState(30);
  const [newPostMax, setNewPostMax] = useState(60);
  const [autoPostRunning, setAutoPostRunning] = useState(false);

  // --- Reply config state ---
  const [replyTemplates, setReplyTemplates] = useState<ReplyTemplate[]>([]);
  const [newReplyContent, setNewReplyContent] = useState("");

  // --- Nick settings state ---
  const [settings, setSettings] = useState<NickLiveSettings | null>(null);

  // --- Moderator state ---
  const [modStatus, setModStatus] = useState<ModeratorStatus | null>(null);
  const [curlText, setCurlText] = useState("");
  const [modSaving, setModSaving] = useState(false);

  // --- Knowledge products state ---
  const [products, setProducts] = useState<KnowledgeProduct[]>([]);
  const [parseLoading, setParseLoading] = useState(false);

  // --- Debounce refs ---
  const debounceTimers = useRef<Record<number, ReturnType<typeof setTimeout>>>({});

  // --- Load all data on open ---
  useEffect(() => {
    if (!open) return;

    const load = async () => {
      try {
        const [host, templates, replies, nickSettings, autoStatus, mod, kps] =
          await Promise.all([
            getHostStatus(nickLiveId),
            getAutoPostTemplates(nickLiveId),
            getReplyTemplates(nickLiveId),
            getNickSettings(nickLiveId),
            getAutoPostStatus(nickLiveId),
            getModeratorStatus(nickLiveId),
            getKnowledgeProducts(nickLiveId),
          ]);

        setHostStatus(host);
        setProxy(host.proxy ?? "");
        setAutoPostTemplates(templates);
        setReplyTemplates(replies);
        setSettings(nickSettings);
        setAutoPostRunning(autoStatus.running);
        setModStatus(mod);
        setProducts(kps);
      } catch {
        message.error("Failed to load nick configuration");
      }
    };

    load();
  }, [open, nickLiveId]);

  // --- Cleanup debounce timers ---
  useEffect(() => {
    const timers = debounceTimers.current;
    return () => {
      Object.values(timers).forEach(clearTimeout);
    };
  }, []);

  // --- Host Config handlers ---
  const handleGetCredentials = useCallback(async () => {
    setHostLoading(true);
    try {
      if (proxy) {
        await updateNickSettings(nickLiveId, { host_proxy: proxy });
      }
      const result = await getHostCredentials(nickLiveId);
      setHostStatus(result);
      message.success("Credentials retrieved");
    } catch {
      message.error("Failed to get credentials");
    } finally {
      setHostLoading(false);
    }
  }, [nickLiveId, proxy]);

  // --- Auto-post handlers ---
  const handleAddAutoPostTemplate = useCallback(async () => {
    if (!newPostContent.trim()) return;
    try {
      const created = await createAutoPostTemplate(
        nickLiveId,
        newPostContent.trim(),
        newPostMin,
        newPostMax
      );
      setAutoPostTemplates((prev) => [...prev, created]);
      setNewPostContent("");
      message.success("Template added");
    } catch {
      message.error("Failed to add template");
    }
  }, [nickLiveId, newPostContent, newPostMin, newPostMax]);

  const handleDeleteAutoPostTemplate = useCallback(
    async (templateId: number) => {
      try {
        await deleteAutoPostTemplate(nickLiveId, templateId);
        setAutoPostTemplates((prev) => prev.filter((t) => t.id !== templateId));
        message.success("Template deleted");
      } catch {
        message.error("Failed to delete template");
      }
    },
    [nickLiveId]
  );

  const handleUpdateInterval = useCallback(
    (templateId: number, field: "min_interval_seconds" | "max_interval_seconds", value: number) => {
      if (debounceTimers.current[templateId]) {
        clearTimeout(debounceTimers.current[templateId]);
      }

      setAutoPostTemplates((prev) =>
        prev.map((t) => (t.id === templateId ? { ...t, [field]: value } : t))
      );

      debounceTimers.current[templateId] = setTimeout(async () => {
        try {
          await updateAutoPostTemplate(nickLiveId, templateId, { [field]: value });
        } catch {
          message.error("Failed to update interval");
        }
      }, 800);
    },
    [nickLiveId]
  );

  const handleStartAutoPost = useCallback(async () => {
    if (!sessionId) {
      message.warning("No active session");
      return;
    }
    try {
      await startAutoPost(nickLiveId, String(sessionId));
      setAutoPostRunning(true);
      message.success("Auto-post started");
    } catch {
      message.error("Failed to start auto-post");
    }
  }, [nickLiveId, sessionId]);

  const handleStopAutoPost = useCallback(async () => {
    try {
      await stopAutoPost(nickLiveId);
      setAutoPostRunning(false);
      message.success("Auto-post stopped");
    } catch {
      message.error("Failed to stop auto-post");
    }
  }, [nickLiveId]);

  // --- Reply template handlers ---
  const handleAddReplyTemplate = useCallback(async () => {
    if (!newReplyContent.trim()) return;
    try {
      const created = await createReplyTemplate(nickLiveId, newReplyContent.trim());
      setReplyTemplates((prev) => [...prev, created]);
      setNewReplyContent("");
      message.success("Reply template added");
    } catch {
      message.error("Failed to add reply template");
    }
  }, [nickLiveId, newReplyContent]);

  const handleDeleteReplyTemplate = useCallback(
    async (templateId: number) => {
      try {
        await deleteReplyTemplate(nickLiveId, templateId);
        setReplyTemplates((prev) => prev.filter((t) => t.id !== templateId));
        message.success("Reply template deleted");
      } catch {
        message.error("Failed to delete reply template");
      }
    },
    [nickLiveId]
  );

  // --- Settings update handler ---
  const handleUpdateSettings = useCallback(
    async (patch: NickLiveSettingsUpdate) => {
      try {
        const updated = await updateNickSettings(nickLiveId, patch);
        setSettings(updated);
        message.success("Đã cập nhật");
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail;
        message.error(detail || "Cập nhật thất bại");
      }
    },
    [nickLiveId]
  );

  // --- Knowledge handlers ---
  const handleParseProducts = useCallback(async () => {
    if (!sessionId) {
      message.warning("Chưa có session đang live");
      return;
    }
    setParseLoading(true);
    try {
      const data = await parseKnowledgeProducts(nickLiveId, Number(sessionId));
      setProducts(data);
      message.success(`Parse thành công ${data.length} sản phẩm`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail || "Parse thất bại");
    } finally {
      setParseLoading(false);
    }
  }, [nickLiveId, sessionId]);

  const handleDeleteAllProducts = useCallback(async () => {
    try {
      await deleteKnowledgeProducts(nickLiveId);
      setProducts([]);
      message.success("Đã xóa tất cả sản phẩm");
    } catch {
      message.error("Xóa thất bại");
    }
  }, [nickLiveId]);

  // --- Moderator handlers ---
  const handleSaveCurl = useCallback(async () => {
    if (!curlText.trim()) return;
    setModSaving(true);
    try {
      await saveModeratorCurl(nickLiveId, curlText.trim());
      const updated = await getModeratorStatus(nickLiveId);
      setModStatus(updated);
      setCurlText("");
      message.success("Moderator cURL saved");
    } catch {
      message.error("Failed to save moderator cURL");
    } finally {
      setModSaving(false);
    }
  }, [nickLiveId, curlText]);

  // --- Tab items ---
  const tabItems = [
    {
      key: "host",
      label: "Host Config",
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Proxy (optional)</Text>
            <Input
              placeholder="http:host:port:user:pass"
              value={proxy}
              onChange={(e) => setProxy(e.target.value)}
              style={{ marginTop: 4 }}
            />
          </div>

          <div>
            <Text strong>Status: </Text>
            {hostStatus?.configured ? (
              <Tag color="green">UUID: {hostStatus.uuid}</Tag>
            ) : (
              <Tag color="default">Chua co</Tag>
            )}
          </div>

          <Space>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={hostLoading}
              onClick={handleGetCredentials}
            >
              {hostStatus?.configured ? "Get lai" : "Get Credentials"}
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      key: "autopost",
      label: "Auto-post",
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space align="center">
            <Text strong>Auto-post enabled:</Text>
            <Switch
              checked={settings?.auto_post_enabled ?? false}
              onChange={(val) => handleUpdateSettings({ auto_post_enabled: val })}
            />
          </Space>
          <Space align="center">
            <Text>Gửi tới Host:</Text>
            <Switch
              checked={settings?.auto_post_to_host ?? false}
              disabled={!hostStatus?.configured}
              onChange={(val) => handleUpdateSettings({ auto_post_to_host: val })}
            />
            {!hostStatus?.configured && (
              <Tag color="default">Chưa có host config</Tag>
            )}
          </Space>
          <Space align="center">
            <Text>Gửi tới Moderator:</Text>
            <Switch
              checked={settings?.auto_post_to_moderator ?? false}
              disabled={!modStatus?.configured}
              onChange={(val) => handleUpdateSettings({ auto_post_to_moderator: val })}
            />
            {!modStatus?.configured && (
              <Tag color="default">Chưa có moderator config</Tag>
            )}
          </Space>

          <Space>
            {autoPostRunning ? (
              <Button
                danger
                icon={<PauseCircleOutlined />}
                onClick={handleStopAutoPost}
              >
                Stop
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleStartAutoPost}
              >
                Start
              </Button>
            )}
          </Space>

          <Divider style={{ margin: "8px 0" }} />

          <Title level={5} style={{ margin: 0 }}>
            Templates
          </Title>

          <Space direction="vertical" style={{ width: "100%" }}>
            <TextArea
              rows={2}
              placeholder="Auto-post content..."
              value={newPostContent}
              onChange={(e) => setNewPostContent(e.target.value)}
            />
            <Space>
              <Text>Min (s):</Text>
              <InputNumber
                min={5}
                value={newPostMin}
                onChange={(v) => setNewPostMin(v ?? 30)}
                style={{ width: 80 }}
              />
              <Text>Max (s):</Text>
              <InputNumber
                min={5}
                value={newPostMax}
                onChange={(v) => setNewPostMax(v ?? 60)}
                style={{ width: 80 }}
              />
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleAddAutoPostTemplate}
              >
                Add
              </Button>
            </Space>
          </Space>

          <List
            size="small"
            dataSource={autoPostTemplates}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="del"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => handleDeleteAutoPostTemplate(item.id)}
                  />,
                ]}
              >
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Text>{item.content}</Text>
                  <Space>
                    <Text type="secondary">Min:</Text>
                    <InputNumber
                      size="small"
                      min={5}
                      value={item.min_interval_seconds}
                      onChange={(v) =>
                        handleUpdateInterval(item.id, "min_interval_seconds", v ?? 5)
                      }
                      style={{ width: 70 }}
                    />
                    <Text type="secondary">Max:</Text>
                    <InputNumber
                      size="small"
                      min={5}
                      value={item.max_interval_seconds}
                      onChange={(v) =>
                        handleUpdateInterval(item.id, "max_interval_seconds", v ?? 10)
                      }
                      style={{ width: 70 }}
                    />
                  </Space>
                </Space>
              </List.Item>
            )}
          />
        </Space>
      ),
    },
    {
      key: "reply",
      label: "Reply Config",
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space direction="vertical" style={{ width: "100%" }}>
            <Space align="center">
              <Text strong>Chế độ reply:</Text>
              <Select<ReplyMode>
                style={{ width: 220 }}
                value={settings?.reply_mode ?? "none"}
                onChange={(val) => handleUpdateSettings({ reply_mode: val })}
                options={[
                  { value: "none", label: "None (tắt)" },
                  { value: "knowledge", label: "Knowledge AI" },
                  { value: "ai", label: "AI thường" },
                  { value: "template", label: "Template" },
                ]}
              />
            </Space>
            <Text type="secondary">Kênh gửi reply:</Text>
            <Space align="center">
              <Text>Host channel:</Text>
              <Switch
                checked={settings?.reply_to_host ?? false}
                disabled={!hostStatus?.configured}
                onChange={(val) => handleUpdateSettings({ reply_to_host: val })}
              />
              {!hostStatus?.configured && (
                <Tag color="default">Chưa có host config</Tag>
              )}
            </Space>
            <Space align="center">
              <Text>Moderator channel:</Text>
              <Switch
                checked={settings?.reply_to_moderator ?? false}
                disabled={!modStatus?.configured}
                onChange={(val) => handleUpdateSettings({ reply_to_moderator: val })}
              />
              {!modStatus?.configured && (
                <Tag color="default">Chưa có moderator config</Tag>
              )}
            </Space>
          </Space>

          <Divider style={{ margin: "8px 0" }} />

          <Title level={5} style={{ margin: 0 }}>
            Reply Templates
          </Title>

          <Space style={{ width: "100%" }}>
            <Input
              placeholder="Reply template content..."
              value={newReplyContent}
              onChange={(e) => setNewReplyContent(e.target.value)}
              onPressEnter={handleAddReplyTemplate}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleAddReplyTemplate}
            >
              Add
            </Button>
          </Space>

          <List
            size="small"
            dataSource={replyTemplates}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="del"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => handleDeleteReplyTemplate(item.id)}
                  />,
                ]}
              >
                <Text>{item.content}</Text>
              </List.Item>
            )}
          />
        </Space>
      ),
    },
    {
      key: "knowledge",
      label: "Knowledge",
      children: (() => {
        const parseKeywords = (raw: string): string[] => {
          try {
            const p = JSON.parse(raw);
            return Array.isArray(p) ? p : [];
          } catch {
            return [];
          }
        };
        const parseJsonArr = (raw: string | null): string[] => {
          if (!raw) return [];
          try {
            const p = JSON.parse(raw);
            return Array.isArray(p) ? p : [];
          } catch {
            return [];
          }
        };
        const formatPrice = (v: number | null): string =>
          v === null ? "-" : `${v.toLocaleString("vi-VN")}đ`;

        const columns: ColumnsType<KnowledgeProduct> = [
          { title: "#", dataIndex: "product_order", width: 50 },
          { title: "Tên", dataIndex: "name", ellipsis: true, width: 220 },
          {
            title: "Keywords",
            dataIndex: "keywords",
            width: 180,
            render: (val: string) =>
              parseKeywords(val).map((kw, i) => (
                <Tag key={i} color="blue">
                  {kw}
                </Tag>
              )),
          },
          {
            title: "Giá",
            width: 130,
            render: (_: unknown, r: KnowledgeProduct) => {
              const price =
                r.price_min === r.price_max
                  ? formatPrice(r.price_min)
                  : `${formatPrice(r.price_min)} - ${formatPrice(r.price_max)}`;
              return (
                <span>
                  {price}
                  {r.discount_pct ? (
                    <Tag color="red" style={{ marginLeft: 4 }}>
                      -{r.discount_pct}%
                    </Tag>
                  ) : null}
                </span>
              );
            },
          },
          {
            title: "KM",
            width: 140,
            render: (_: unknown, r: KnowledgeProduct) => {
              const vs = parseJsonArr(r.voucher_info);
              if (!vs.length) return "-";
              return (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
                  {vs.map((v, i) => (
                    <Tag key={i} color="orange">
                      {v}
                    </Tag>
                  ))}
                </div>
              );
            },
          },
          {
            title: "Tồn",
            dataIndex: "stock_qty",
            width: 70,
            render: (val: number | null, r: KnowledgeProduct) => (
              <Tag color={r.in_stock ? "green" : "red"}>
                {r.in_stock ? val ?? "Có" : "Hết"}
              </Tag>
            ),
          },
        ];

        return (
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <Space align="center">
              <Text strong>
                <DatabaseOutlined /> {products.length} sản phẩm
              </Text>
              <Button
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={parseLoading}
                disabled={!sessionId}
                onClick={handleParseProducts}
              >
                Parse sản phẩm
              </Button>
              {products.length > 0 && (
                <Popconfirm
                  title="Xóa tất cả sản phẩm?"
                  onConfirm={handleDeleteAllProducts}
                  okText="Xóa"
                  cancelText="Hủy"
                >
                  <Button danger icon={<DeleteOutlined />}>
                    Xóa tất cả
                  </Button>
                </Popconfirm>
              )}
            </Space>
            {!sessionId && (
              <Text type="secondary">
                Cần có phiên live đang scan để parse sản phẩm từ Relive.
              </Text>
            )}
            {products.length > 0 && (
              <Table
                dataSource={products}
                columns={columns}
                rowKey="pk"
                size="small"
                pagination={false}
                scroll={{ x: 800, y: 400 }}
              />
            )}
          </Space>
        );
      })(),
    },
    {
      key: "moderator",
      label: "Moderator",
      children: (
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <div>
            <Text strong>Status: </Text>
            {modStatus?.configured ? (
              <Tag color="green">Configured (Host: {modStatus.host_id})</Tag>
            ) : (
              <Tag color="default">Not configured</Tag>
            )}
          </div>

          <div>
            <Text strong>Paste cURL</Text>
            <TextArea
              rows={4}
              placeholder="curl 'https://...' -H 'authority: ...' ..."
              value={curlText}
              onChange={(e) => setCurlText(e.target.value)}
              style={{ marginTop: 4 }}
            />
          </div>

          <Button
            type="primary"
            loading={modSaving}
            onClick={handleSaveCurl}
            disabled={!curlText.trim()}
          >
            Save cURL
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Modal
      title={`Config: ${nickName}`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={700}
      destroyOnClose
    >
      <Tabs items={tabItems} />
    </Modal>
  );
}
