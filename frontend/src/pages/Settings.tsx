// frontend/src/pages/Settings.tsx
import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  Input,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { ThunderboltOutlined } from "@ant-design/icons";
import {
  getOpenAIConfig,
  getReliveApiKey,
  getSystemPrompt,
  testAI,
  updateOpenAIConfig,
  updateReliveApiKey,
  updateSystemPrompt,
} from "../api/settings";
import {
  getBannedWords,
  getKnowledgeAIConfig,
  updateBannedWords,
  updateKnowledgeAIConfig,
} from "../api/knowledge";

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
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  // System prompt
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);

  // Relive API key — never store the current value; only track whether one is configured
  const [reliveKey, setReliveKey] = useState("");
  const [reliveKeySet, setReliveKeySet] = useState(false);
  const [reliveLoading, setReliveLoading] = useState(false);

  // Knowledge AI config
  const [knowledgePrompt, setKnowledgePrompt] = useState("");
  const [knowledgeModel, setKnowledgeModel] = useState("gpt-4o");
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);

  // Banned words
  const [bannedWordsText, setBannedWordsText] = useState("");
  const [bannedWordsLoading, setBannedWordsLoading] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [oai, prompt, banned, kbConfig] = await Promise.all([
        getOpenAIConfig(),
        getSystemPrompt(),
        getBannedWords(),
        getKnowledgeAIConfig(),
      ]);
      setApiKeySet(oai.api_key_set);
      setModel(oai.model || "gpt-4o");
      setSystemPrompt(prompt.prompt);
      setBannedWordsText(banned.words.join("\n"));
      setKnowledgePrompt(kbConfig.system_prompt);
      setKnowledgeModel(kbConfig.model || "gpt-4o");
    } catch {
      message.error("Không thể tải cài đặt");
    }

    getReliveApiKey().then((r) => {
      setReliveKeySet(r.api_key_set);
      // Never populate the input with the stored key value.
      setReliveKey("");
    });
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

  const handleTestAI = async () => {
    setTestLoading(true);
    setTestResult(null);
    try {
      const result = await testAI();
      setTestResult(`[${result.model}] ${result.reply}`);
      message.success("AI hoạt động!");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setTestResult(null);
      message.error(detail || "Test AI thất bại");
    } finally {
      setTestLoading(false);
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

  const handleSaveReliveKey = async () => {
    setReliveLoading(true);
    try {
      await updateReliveApiKey(reliveKey);
      setReliveKeySet(!!reliveKey);
      message.success("Relive API key saved");
    } catch {
      message.error("Failed to save");
    } finally {
      setReliveLoading(false);
    }
  };

  const handleSaveKnowledgeConfig = async () => {
    setKnowledgeLoading(true);
    try {
      await updateKnowledgeAIConfig({
        system_prompt: knowledgePrompt,
        model: knowledgeModel,
      });
      message.success("Đã lưu cấu hình Knowledge AI");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setKnowledgeLoading(false);
    }
  };

  const handleSaveBannedWords = async () => {
    setBannedWordsLoading(true);
    try {
      const words = bannedWordsText
        .split("\n")
        .map((w) => w.trim())
        .filter((w) => w.length > 0);
      await updateBannedWords(words);
      message.success("Đã lưu từ cấm");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setBannedWordsLoading(false);
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
          <Space>
            <Button type="primary" onClick={handleSaveOpenAI} loading={openaiLoading}>
              Lưu cấu hình OpenAI
            </Button>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={handleTestAI}
              loading={testLoading}
              disabled={!apiKeySet}
            >
              Test AI
            </Button>
          </Space>
          {testResult && (
            <Card size="small" style={{ marginTop: 8, background: "#f6ffed" }}>
              <Text strong>AI reply: </Text>
              <Text>{testResult}</Text>
            </Card>
          )}
        </Space>
      </Card>

      {/* Relive.vn API Key */}
      <Card title="Relive.vn API Key" style={{ marginBottom: 16 }}>
        {reliveKeySet && (
          <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
            <Tag color="green">Đã cấu hình</Tag> Nhập key mới bên dưới để thay thế.
          </Text>
        )}
        <Space>
          <Input.Password
            placeholder={reliveKeySet ? "Nhập key mới để thay thế" : "Relive API key"}
            value={reliveKey}
            onChange={(e) => setReliveKey(e.target.value)}
            style={{ width: 400 }}
          />
          <Button type="primary" onClick={handleSaveReliveKey} loading={reliveLoading}>
            Save
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

      {/* Knowledge AI Config */}
      <Card title="Cấu hình Knowledge AI (AI + dữ liệu sản phẩm)" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          Cấu hình riêng cho chế độ Knowledge Reply. AI sẽ dùng prompt này kết hợp với
          thông tin sản phẩm để trả lời comment trong Shopee Live.
        </Text>
        <Space direction="vertical" style={{ width: "100%" }}>
          <TextArea
            rows={5}
            placeholder="Ví dụ: Bạn là nhân viên tư vấn trên Shopee Live. Trả lời ngắn gọn, thân thiện, có emoji phù hợp. Dựa vào thông tin sản phẩm để tư vấn chính xác."
            value={knowledgePrompt}
            onChange={(e) => setKnowledgePrompt(e.target.value)}
          />
          <Space>
            <Text>Model:</Text>
            <Select
              style={{ width: 200 }}
              value={knowledgeModel}
              options={OPENAI_MODELS}
              onChange={setKnowledgeModel}
            />
          </Space>
          <Button
            type="primary"
            onClick={handleSaveKnowledgeConfig}
            loading={knowledgeLoading}
          >
            Lưu cấu hình Knowledge AI
          </Button>
        </Space>
      </Card>

      {/* Banned Words */}
      <Card title="Từ cấm (Banned Words)" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          Các từ này sẽ được thay thế bằng *** trong reply AI. Mỗi từ 1 dòng.
        </Text>
        <TextArea
          rows={4}
          placeholder={"Nhập từ cấm, mỗi từ 1 dòng\nVí dụ:\ngiá rẻ nhất\ncam kết chính hãng"}
          value={bannedWordsText}
          onChange={(e) => setBannedWordsText(e.target.value)}
        />
        <Button
          type="primary"
          onClick={handleSaveBannedWords}
          loading={bannedWordsLoading}
          style={{ marginTop: 8 }}
        >
          Lưu từ cấm
        </Button>
      </Card>
    </div>
  );
}

export default Settings;
