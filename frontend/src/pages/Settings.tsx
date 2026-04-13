// frontend/src/pages/Settings.tsx
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  Input,
  InputNumber,
  List,
  Select,
  Space,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import {
  type AutoPostTemplate,
  type ReplyTemplate,
  createAutoPostTemplate,
  createReplyTemplate,
  deleteAutoPostTemplate,
  deleteReplyTemplate,
  getAutoPostTemplates,
  getOpenAIConfig,
  getReplyTemplates,
  getSystemPrompt,
  updateAutoPostTemplate,
  updateOpenAIConfig,
  updateSystemPrompt,
} from "../api/settings";

const { Title, Text } = Typography;
const { TextArea } = Input;

const OPENAI_MODELS = [
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
];

function Settings() {
  // OpenAI
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [apiKeySet, setApiKeySet] = useState(false);
  const [openaiLoading, setOpenaiLoading] = useState(false);

  // System prompt
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);

  // Reply templates
  const [replyTemplates, setReplyTemplates] = useState<ReplyTemplate[]>([]);
  const [newReplyContent, setNewReplyContent] = useState("");
  const [replyLoading, setReplyLoading] = useState(false);

  // Auto-post templates
  const [autoPostTemplates, setAutoPostTemplates] = useState<AutoPostTemplate[]>([]);
  const [newPostContent, setNewPostContent] = useState("");
  const [newPostMin, setNewPostMin] = useState(60);
  const [newPostMax, setNewPostMax] = useState(300);
  const [postLoading, setPostLoading] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [oai, prompt, replies, posts] = await Promise.all([
        getOpenAIConfig(),
        getSystemPrompt(),
        getReplyTemplates(),
        getAutoPostTemplates(),
      ]);
      setApiKeySet(oai.api_key_set);
      setModel(oai.model || "gpt-4o");
      setSystemPrompt(prompt.prompt);
      setReplyTemplates(replies);
      setAutoPostTemplates(posts);
    } catch {
      message.error("Không thể tải cài đặt");
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleSaveOpenAI = async () => {
    if (!apiKey.trim()) {
      message.error("Nhập API key");
      return;
    }
    setOpenaiLoading(true);
    try {
      await updateOpenAIConfig(apiKey, model);
      message.success("Đã lưu cấu hình OpenAI");
      setApiKey("");
      await loadAll();
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setOpenaiLoading(false);
    }
  };

  const handleSavePrompt = async () => {
    setPromptLoading(true);
    try {
      await updateSystemPrompt(systemPrompt);
      message.success("Đã lưu system prompt");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setPromptLoading(false);
    }
  };

  const handleAddReplyTemplate = async () => {
    if (!newReplyContent.trim()) return;
    setReplyLoading(true);
    try {
      await createReplyTemplate(newReplyContent);
      setNewReplyContent("");
      const updated = await getReplyTemplates();
      setReplyTemplates(updated);
    } catch {
      message.error("Thêm thất bại");
    } finally {
      setReplyLoading(false);
    }
  };

  const handleDeleteReplyTemplate = async (id: number) => {
    try {
      await deleteReplyTemplate(id);
      setReplyTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const handleAddAutoPost = async () => {
    if (!newPostContent.trim()) return;
    if (newPostMin > newPostMax) {
      message.error("Min phải nhỏ hơn Max");
      return;
    }
    setPostLoading(true);
    try {
      await createAutoPostTemplate(newPostContent, newPostMin, newPostMax);
      setNewPostContent("");
      setNewPostMin(60);
      setNewPostMax(300);
      const updated = await getAutoPostTemplates();
      setAutoPostTemplates(updated);
    } catch {
      message.error("Thêm thất bại");
    } finally {
      setPostLoading(false);
    }
  };

  const handleDeleteAutoPost = async (id: number) => {
    try {
      await deleteAutoPostTemplate(id);
      setAutoPostTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const handleUpdateAutoPostInterval = async (
    id: number,
    min_interval_seconds: number,
    max_interval_seconds: number
  ) => {
    try {
      const updated = await updateAutoPostTemplate(id, { min_interval_seconds, max_interval_seconds });
      setAutoPostTemplates((prev) => prev.map((t) => (t.id === id ? updated : t)));
    } catch {
      message.error("Cập nhật thất bại");
    }
  };

  return (
    <div>
      <Title level={3}>Cài đặt</Title>

      {/* OpenAI Config */}
      <Card title="Cấu hình OpenAI" style={{ marginBottom: 16 }}>
        {apiKeySet && (
          <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
            API Key đã được lưu. Nhập key mới để thay thế.
          </Text>
        )}
        <Space direction="vertical" style={{ width: "100%" }}>
          <Input.Password
            placeholder="Nhập OpenAI API Key (sk-...)"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <Select
            style={{ width: 200 }}
            value={model}
            options={OPENAI_MODELS}
            onChange={setModel}
          />
          <Button type="primary" onClick={handleSaveOpenAI} loading={openaiLoading}>
            Lưu cấu hình OpenAI
          </Button>
        </Space>
      </Card>

      {/* System Prompt */}
      <Card title="System Prompt (Prompt cha cho AI)" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          AI sẽ dùng prompt này để trả lời comment của khách hàng.
        </Text>
        <TextArea
          rows={5}
          placeholder="Ví dụ: Bạn là nhân viên CSKH của shop trên Shopee Live. Hãy trả lời ngắn gọn, thân thiện và đúng trọng tâm câu hỏi của khách."
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
        />
        <Button
          type="primary"
          onClick={handleSavePrompt}
          loading={promptLoading}
          style={{ marginTop: 8 }}
        >
          Lưu System Prompt
        </Button>
      </Card>

      {/* Reply Templates */}
      <Card
        title="Reply Templates (Non-AI mode)"
        style={{ marginBottom: 16 }}
        extra={<Text type="secondary">Chọn ngẫu nhiên khi AI tắt</Text>}
      >
        <Space.Compact style={{ width: "100%", marginBottom: 12 }}>
          <Input
            placeholder="Thêm câu reply mới (VD: Cảm ơn bạn đã quan tâm!)"
            value={newReplyContent}
            onChange={(e) => setNewReplyContent(e.target.value)}
            onPressEnter={handleAddReplyTemplate}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleAddReplyTemplate}
            loading={replyLoading}
          >
            Thêm
          </Button>
        </Space.Compact>
        <List
          dataSource={replyTemplates}
          locale={{ emptyText: "Chưa có template nào" }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="del"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  size="small"
                  onClick={() => handleDeleteReplyTemplate(item.id)}
                />,
              ]}
            >
              <Text>{item.content}</Text>
            </List.Item>
          )}
        />
      </Card>

      {/* Auto-post Templates */}
      <Card
        title="Auto-post Templates (Đăng comment theo lịch)"
        style={{ marginBottom: 16 }}
        extra={<Text type="secondary">Xoay vòng, interval ngẫu nhiên trong khoảng min~max</Text>}
      >
        <Space direction="vertical" style={{ width: "100%", marginBottom: 12 }}>
          <TextArea
            rows={2}
            placeholder="Nội dung comment (VD: Mua ngay giảm 50%! 🔥)"
            value={newPostContent}
            onChange={(e) => setNewPostContent(e.target.value)}
          />
          <Space>
            <Text>Interval:</Text>
            <InputNumber
              min={10}
              max={86400}
              value={newPostMin}
              onChange={(v) => setNewPostMin(v || 60)}
              addonAfter="s min"
            />
            <InputNumber
              min={10}
              max={86400}
              value={newPostMax}
              onChange={(v) => setNewPostMax(v || 300)}
              addonAfter="s max"
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleAddAutoPost}
              loading={postLoading}
            >
              Thêm
            </Button>
          </Space>
        </Space>
        <List
          dataSource={autoPostTemplates}
          locale={{ emptyText: "Chưa có template nào" }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button
                  key="del"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  size="small"
                  onClick={() => handleDeleteAutoPost(item.id)}
                />,
              ]}
            >
              <Space direction="vertical" size="small" style={{ flex: 1 }}>
                <Text>{item.content}</Text>
                <Space size="small">
                  <Text type="secondary" style={{ fontSize: 12 }}>Interval:</Text>
                  <InputNumber
                    min={10}
                    size="small"
                    value={item.min_interval_seconds}
                    onChange={(v) =>
                      handleUpdateAutoPostInterval(item.id, v || 10, item.max_interval_seconds)
                    }
                    addonAfter="s"
                  />
                  <Text type="secondary">~</Text>
                  <InputNumber
                    min={10}
                    size="small"
                    value={item.max_interval_seconds}
                    onChange={(v) =>
                      handleUpdateAutoPostInterval(item.id, item.min_interval_seconds, v || 10)
                    }
                    addonAfter="s"
                  />
                </Space>
              </Space>
            </List.Item>
          )}
        />
      </Card>
    </div>
  );
}

export default Settings;
