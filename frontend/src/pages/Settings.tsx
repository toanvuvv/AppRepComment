// frontend/src/pages/Settings.tsx
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
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
  getSystemPrompt,
  testAI,
  updateOpenAIConfig,
  updateSystemPrompt,
  type AiKeyMode,
} from "../api/settings";
import {
  getBannedWords,
  getKnowledgeAIConfig,
  updateBannedWords,
  updateKnowledgeAIConfig,
} from "../api/knowledge";
import {
  getSystemKeys,
  updateSystemOpenAI,
  updateSystemRelive,
  type SystemKeysStatus,
} from "../api/admin";
import apiClient from "../api/client";

const { Title, Text } = Typography;
const { TextArea } = Input;

const OPENAI_MODELS = [
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
];

interface Me {
  id: number;
  username: string;
  role: "admin" | "user";
  ai_key_mode: AiKeyMode;
}

function Settings() {
  // Identity
  const [me, setMe] = useState<Me | null>(null);

  // Per-user OpenAI (own mode only)
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [apiKeySet, setApiKeySet] = useState(false);
  const [openaiLoading, setOpenaiLoading] = useState(false);
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  // System prompt
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptLoading, setPromptLoading] = useState(false);

  // Knowledge AI config
  const [knowledgePrompt, setKnowledgePrompt] = useState("");
  const [knowledgeModel, setKnowledgeModel] = useState("gpt-4o");
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);

  // Banned words
  const [bannedWordsText, setBannedWordsText] = useState("");
  const [bannedWordsLoading, setBannedWordsLoading] = useState(false);

  // Admin-only: system keys
  const [sysKeys, setSysKeys] = useState<SystemKeysStatus | null>(null);
  const [sysRelive, setSysRelive] = useState("");
  const [sysOpenAIKey, setSysOpenAIKey] = useState("");
  const [sysOpenAIModel, setSysOpenAIModel] = useState("gpt-4o");
  const [sysReliveLoading, setSysReliveLoading] = useState(false);
  const [sysOpenAILoading, setSysOpenAILoading] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const meRes = await apiClient.get<Me>("/auth/me");
      setMe(meRes.data);

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

      if (meRes.data.role === "admin") {
        const sk = await getSystemKeys();
        setSysKeys(sk);
        setSysOpenAIModel(sk.openai_model || "gpt-4o");
      }
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

  const handleTestAI = async () => {
    setTestLoading(true);
    setTestResult(null);
    try {
      const result = await testAI();
      setTestResult(`[${result.model}] ${result.reply}`);
      message.success("AI hoạt động!");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response
        ?.data?.detail;
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

  const handleSaveSysRelive = async () => {
    if (!sysRelive.trim()) {
      message.error("Nhập Relive API key");
      return;
    }
    setSysReliveLoading(true);
    try {
      await updateSystemRelive(sysRelive);
      setSysRelive("");
      await loadAll();
      message.success("Đã lưu System Relive key");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setSysReliveLoading(false);
    }
  };

  const handleSaveSysOpenAI = async () => {
    if (!sysOpenAIKey.trim()) {
      message.error("Nhập System OpenAI API key");
      return;
    }
    setSysOpenAILoading(true);
    try {
      await updateSystemOpenAI(sysOpenAIKey, sysOpenAIModel);
      setSysOpenAIKey("");
      await loadAll();
      message.success("Đã lưu System OpenAI key");
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setSysOpenAILoading(false);
    }
  };

  if (!me) return null;
  const isAdmin = me.role === "admin";
  const usingSystemKey = me.ai_key_mode === "system";

  return (
    <div>
      <Title level={3}>Cài đặt</Title>

      {/* Per-user OpenAI Config — hidden entirely in system mode */}
      {usingSystemKey ? (
        <Card style={{ marginBottom: 16 }}>
          <Space direction="vertical">
            <Space>
              <Tag color="blue">AI key: hệ thống</Tag>
              <Text>Tài khoản đang dùng OpenAI key do admin cấu hình.</Text>
            </Space>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={handleTestAI}
              loading={testLoading}
            >
              Test AI (dùng key hệ thống)
            </Button>
            {testResult && (
              <Card size="small" style={{ marginTop: 8, background: "#f6ffed" }}>
                <Text strong>AI reply: </Text>
                <Text>{testResult}</Text>
              </Card>
            )}
          </Space>
        </Card>
      ) : (
        <Card title="Cấu hình OpenAI (key riêng)" style={{ marginBottom: 16 }}>
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
      )}

      {/* System Prompt */}
      <Card title="System Prompt (Prompt cha cho AI)" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          AI sẽ dùng prompt này để trả lời comment của khách hàng.
        </Text>
        <TextArea
          rows={5}
          placeholder="Ví dụ: Bạn là nhân viên CSKH..."
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
          Cấu hình riêng cho chế độ Knowledge Reply.
        </Text>
        <Space direction="vertical" style={{ width: "100%" }}>
          <TextArea
            rows={5}
            placeholder="Ví dụ: Bạn là nhân viên tư vấn trên Shopee Live..."
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
          <Button type="primary" onClick={handleSaveKnowledgeConfig} loading={knowledgeLoading}>
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
          placeholder={"Nhập từ cấm, mỗi từ 1 dòng"}
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

      {/* Admin-only: System Keys */}
      {isAdmin && (
        <>
          <Title level={4} style={{ marginTop: 32 }}>
            System Keys (admin)
          </Title>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="Key hệ thống dùng chung cho toàn bộ user."
            description="Relive key áp dụng cho mọi user. System OpenAI key chỉ dùng cho user được admin gán mode 'system'."
          />

          <Card title="System Relive API Key" style={{ marginBottom: 16 }}>
            {sysKeys?.relive_api_key_set && (
              <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
                <Tag color="green">Đã cấu hình</Tag> Nhập key mới để thay thế.
              </Text>
            )}
            <Space>
              <Input.Password
                placeholder={sysKeys?.relive_api_key_set ? "Nhập key mới để thay thế" : "Relive API key"}
                value={sysRelive}
                onChange={(e) => setSysRelive(e.target.value)}
                style={{ width: 400 }}
              />
              <Button type="primary" onClick={handleSaveSysRelive} loading={sysReliveLoading}>
                Lưu
              </Button>
            </Space>
          </Card>

          <Card title="System OpenAI Key" style={{ marginBottom: 16 }}>
            {sysKeys?.openai_api_key_set && (
              <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
                <Tag color="green">Đã cấu hình</Tag> Nhập key mới để thay thế.
              </Text>
            )}
            <Space direction="vertical" style={{ width: "100%" }}>
              <Input.Password
                placeholder="sk-..."
                value={sysOpenAIKey}
                onChange={(e) => setSysOpenAIKey(e.target.value)}
              />
              <Select
                style={{ width: 200 }}
                value={sysOpenAIModel}
                options={OPENAI_MODELS}
                onChange={setSysOpenAIModel}
              />
              <Button type="primary" onClick={handleSaveSysOpenAI} loading={sysOpenAILoading}>
                Lưu System OpenAI
              </Button>
            </Space>
          </Card>
        </>
      )}
    </div>
  );
}

export default Settings;
