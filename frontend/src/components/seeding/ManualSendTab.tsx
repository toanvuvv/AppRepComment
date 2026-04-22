import { ReactNode, useState } from "react";
import {
  Button,
  Card,
  Input,
  List,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { SendOutlined } from "@ant-design/icons";
import { manualSend } from "../../api/seeding";
import { useSeedingClones } from "../../hooks/useSeedingClones";

const { Text } = Typography;
const { TextArea } = Input;

interface HistoryEntry {
  id: number;
  cloneName: string;
  content: string;
  status: "success" | "failed" | "rate_limited";
  note: string | null;
  time: string;
}

interface ManualSendTabProps {
  nickHostDropdown: ReactNode;
  sessionDropdown: ReactNode;
  selectedNickLiveId: number | null;
  selectedShopeeSessionId: number | null;
}

function statusColor(status: HistoryEntry["status"]): string {
  if (status === "success") return "green";
  if (status === "rate_limited") return "orange";
  return "red";
}

function statusLabel(status: HistoryEntry["status"]): string {
  if (status === "success") return "OK";
  if (status === "rate_limited") return "RATE LIMITED";
  return "FAILED";
}

export function ManualSendTab({
  nickHostDropdown,
  sessionDropdown,
  selectedNickLiveId,
  selectedShopeeSessionId,
}: ManualSendTabProps) {
  const { clones } = useSeedingClones();
  const [selectedCloneId, setSelectedCloneId] = useState<number | null>(null);
  const [content, setContent] = useState("");
  const [sending, setSending] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);

  const cloneOptions = clones.map((c) => ({ value: c.id, label: c.name }));

  const selectedClone = clones.find((c) => c.id === selectedCloneId) ?? null;

  const handleSend = async () => {
    if (!selectedNickLiveId) {
      message.warning("Vui lòng chọn nick host");
      return;
    }
    if (!selectedShopeeSessionId) {
      message.warning("Vui lòng chọn phiên Shopee");
      return;
    }
    if (!selectedCloneId) {
      message.warning("Vui lòng chọn clone");
      return;
    }
    if (!content.trim()) {
      message.warning("Vui lòng nhập nội dung");
      return;
    }

    setSending(true);
    const sentContent = content.trim();

    try {
      const result = await manualSend({
        nick_live_id: selectedNickLiveId,
        shopee_session_id: selectedShopeeSessionId,
        clone_id: selectedCloneId,
        content: sentContent,
      });

      const entry: HistoryEntry = {
        id: result.log_id,
        cloneName: selectedClone?.name ?? String(selectedCloneId),
        content: sentContent,
        status: result.status,
        note: result.error ?? null,
        time: new Date().toLocaleTimeString("vi-VN"),
      };
      setHistory((prev) => [entry, ...prev].slice(0, 10));

      if (result.status === "success") {
        message.success("Gửi thành công");
        setContent("");
      } else {
        message.error(`Gửi thất bại: ${result.error ?? "unknown"}`);
      }
    } catch (err: unknown) {
      const axiosErr = err as {
        response?: { status?: number; data?: { detail?: unknown; retry_after_sec?: number } };
      };
      const status = axiosErr.response?.status;
      const detail = axiosErr.response?.data?.detail;
      const retryAfter =
        axiosErr.response?.data?.retry_after_sec ??
        (detail && typeof detail === "object"
          ? (detail as Record<string, unknown>).retry_after_sec
          : null);

      let note: string | null = null;
      let entryStatus: HistoryEntry["status"] = "failed";

      if (status === 429) {
        entryStatus = "rate_limited";
        note =
          retryAfter != null
            ? `retry sau ${retryAfter}s`
            : "rate limited";
        message.warning(`Rate limited${retryAfter != null ? ` — retry sau ${retryAfter}s` : ""}`);
      } else {
        note =
          typeof detail === "string"
            ? detail
            : err instanceof Error
            ? err.message
            : "unknown error";
        message.error(`Gửi thất bại: ${note}`);
      }

      const entry: HistoryEntry = {
        id: Date.now(),
        cloneName: selectedClone?.name ?? String(selectedCloneId),
        content: sentContent,
        status: entryStatus,
        note,
        time: new Date().toLocaleTimeString("vi-VN"),
      };
      setHistory((prev) => [entry, ...prev].slice(0, 10));
    } finally {
      setSending(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="large">
      <Card title="Gửi seeding thủ công" size="small">
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space wrap>
            <div>
              <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                Nick host
              </Text>
              {nickHostDropdown}
            </div>
            <div>
              <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                Phiên Shopee
              </Text>
              {sessionDropdown}
            </div>
          </Space>

          <div>
            <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
              Clone gửi
            </Text>
            <Select
              style={{ width: 240 }}
              placeholder="Chọn clone"
              value={selectedCloneId}
              onChange={setSelectedCloneId}
              options={cloneOptions}
              showSearch
              optionFilterProp="label"
            />
          </div>

          <div>
            <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
              Nội dung
            </Text>
            <TextArea
              rows={3}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Nhập nội dung comment seeding..."
              maxLength={2000}
              showCount
            />
          </div>

          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            loading={sending}
            disabled={!selectedNickLiveId || !selectedShopeeSessionId || !selectedCloneId || !content.trim()}
          >
            Gửi
          </Button>
        </Space>
      </Card>

      {history.length > 0 && (
        <Card title="Lịch sử gần đây (10 gần nhất)" size="small">
          <List
            size="small"
            dataSource={history}
            renderItem={(item) => (
              <List.Item key={item.id}>
                <Space wrap>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {item.time}
                  </Text>
                  <Tag color={statusColor(item.status)}>
                    {statusLabel(item.status)}
                  </Tag>
                  <Text strong>{item.cloneName}</Text>
                  <Text ellipsis style={{ maxWidth: 200 }}>
                    {item.content}
                  </Text>
                  {item.note && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {item.note}
                    </Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </Card>
      )}
    </Space>
  );
}
