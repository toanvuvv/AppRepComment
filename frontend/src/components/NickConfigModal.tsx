import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  Modal,
  Tabs,
  Button,
  Input,
  InputNumber,
  List,
  Switch,
  Space,
  Typography,
  Tag,
  Divider,
  message,
} from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  ThunderboltOutlined,
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
} from "../api/hostConfig";

import {
  getModeratorStatus,
  saveModeratorCurl,
  type ModeratorStatus,
} from "../api/nickLive";

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

  // --- Debounce refs ---
  const debounceTimers = useRef<Record<number, ReturnType<typeof setTimeout>>>({});

  // --- Load all data on open ---
  useEffect(() => {
    if (!open) return;

    const load = async () => {
      try {
        const [host, templates, replies, nickSettings, autoStatus, mod] =
          await Promise.all([
            getHostStatus(nickLiveId),
            getAutoPostTemplates(nickLiveId),
            getReplyTemplates(nickLiveId),
            getNickSettings(nickLiveId),
            getAutoPostStatus(nickLiveId),
            getModeratorStatus(nickLiveId),
          ]);

        setHostStatus(host);
        setProxy(host.proxy ?? "");
        setAutoPostTemplates(templates);
        setReplyTemplates(replies);
        setSettings(nickSettings);
        setAutoPostRunning(autoStatus.running);
        setModStatus(mod);
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
        await updateNickSettings(nickLiveId, { proxy } as never);
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

  // --- Settings toggle handler ---
  const handleToggleSetting = useCallback(
    async (key: keyof NickLiveSettings, value: boolean) => {
      try {
        const updated = await updateNickSettings(nickLiveId, { [key]: value });
        setSettings(updated);
      } catch {
        message.error("Failed to update setting");
      }
    },
    [nickLiveId]
  );

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
              checked={settings?.host_auto_post_enabled ?? false}
              onChange={(val) => handleToggleSetting("host_auto_post_enabled", val)}
            />
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
              <Text strong>Auto reply:</Text>
              <Switch
                checked={settings?.auto_reply_enabled ?? false}
                onChange={(val) => handleToggleSetting("auto_reply_enabled", val)}
              />
            </Space>
            <Space align="center">
              <Text strong>Host reply:</Text>
              <Switch
                checked={settings?.host_reply_enabled ?? false}
                onChange={(val) => handleToggleSetting("host_reply_enabled", val)}
              />
            </Space>
            <Space align="center">
              <Text strong>AI reply:</Text>
              <Switch
                checked={settings?.ai_reply_enabled ?? false}
                onChange={(val) => handleToggleSetting("ai_reply_enabled", val)}
              />
            </Space>
            <Space align="center">
              <Text strong>Knowledge reply:</Text>
              <Switch
                checked={settings?.knowledge_reply_enabled ?? false}
                onChange={(val) => handleToggleSetting("knowledge_reply_enabled", val)}
              />
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
