import { useEffect, useState } from "react";
import {
  Button,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, ReloadOutlined } from "@ant-design/icons";
import { useReplyLogs } from "../../hooks/useReplyLogs";
import { useReplyLogSessions } from "../../hooks/useReplyLogSessions";
import { deleteReplyLogSession } from "../../api/replyLogs";
import type { ReplyLog, ReplyOutcome, ReplyLogSession } from "../../api/replyLogs";

const { Text } = Typography;

const OUTCOME_COLOR: Record<ReplyOutcome, string> = {
  success: "green",
  failed: "red",
  dropped: "orange",
  circuit_open: "volcano",
  no_config: "default",
};

const OUTCOME_LABEL: Record<ReplyOutcome, string> = {
  success: "OK",
  failed: "FAIL",
  dropped: "DROP",
  circuit_open: "CIRCUIT",
  no_config: "NO CFG",
};

function ReplyLogRow({ log }: { log: ReplyLog }) {
  const time = new Date(log.created_at).toLocaleTimeString("vi-VN");
  const detail =
    log.outcome === "success"
      ? log.reply_text
      : log.error || `status=${log.status_code ?? "?"}`;
  return (
    <div style={{ padding: "4px 0", borderBottom: "1px solid #f0f0f0", fontSize: 13 }}>
      <Space size={6} wrap>
        <Text type="secondary" style={{ fontSize: 11 }}>{time}</Text>
        <Tag color={OUTCOME_COLOR[log.outcome]}>{OUTCOME_LABEL[log.outcome] ?? log.outcome}</Tag>
        {log.reply_type && <Tag>{log.reply_type}</Tag>}
        {log.cached_hit && <Tag color="cyan">cache</Tag>}
        {log.latency_ms !== null && <Tag color="geekblue">{log.latency_ms}ms</Tag>}
        <Text strong style={{ color: "#1677ff" }}>@{log.guest_name || log.guest_id || "?"}</Text>
        {log.comment_text && <Text type="secondary" ellipsis style={{ maxWidth: 220 }}>"{log.comment_text}"</Text>}
        {detail && (
          <Text ellipsis style={{ maxWidth: 320, color: log.outcome === "success" ? "#389e0d" : "#cf1322" }}>
            → {detail}
          </Text>
        )}
      </Space>
    </div>
  );
}

interface ReplyLogsPanelProps {
  nickLiveId: number;
  active: boolean;
}

export default function ReplyLogsPanel({ nickLiveId, active }: ReplyLogsPanelProps) {
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const { sessions, refresh: refreshSessions } = useReplyLogSessions(nickLiveId, active);
  const { logs, stats, refresh: refreshLogs } = useReplyLogs(
    nickLiveId,
    active,
    selectedSessionId,
  );

  useEffect(() => {
    if (!active) return;
    if (sessions.length === 0) { setSelectedSessionId(null); return; }
    if (selectedSessionId === null || !sessions.some((s) => s.session_id === selectedSessionId)) {
      setSelectedSessionId(sessions[0].session_id);
    }
  }, [active, sessions, selectedSessionId]);

  const handleClear = async () => {
    if (selectedSessionId === null) return;
    try {
      const { deleted } = await deleteReplyLogSession(nickLiveId, selectedSessionId);
      message.success(`Đã xóa ${deleted} log của session ${selectedSessionId}`);
      refreshSessions();
      refreshLogs();
    } catch {
      message.error("Không xóa được session log");
    }
  };

  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        {stats && (
          <>
            <Tag color="blue">Tổng: {stats.total}</Tag>
            <Tag color="green">OK: {stats.success}</Tag>
            <Tag color="red">Fail: {stats.failed}</Tag>
            <Tag color="orange">Drop: {stats.dropped}</Tag>
            <Tag>SR: {(stats.success_rate * 100).toFixed(1)}%</Tag>
            {stats.p50_latency_ms !== null && (
              <Tag color="geekblue">p50 {stats.p50_latency_ms}ms / p95 {stats.p95_latency_ms}ms</Tag>
            )}
          </>
        )}
        <Button size="small" icon={<ReloadOutlined />} onClick={refreshLogs}>Refresh</Button>
      </Space>

      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          style={{ minWidth: 360 }}
          value={selectedSessionId}
          placeholder="Chọn session"
          onChange={(v) => setSelectedSessionId(v)}
          options={sessions.map((s: ReplyLogSession) => ({
            value: s.session_id,
            label: `Session #${s.session_id} · ${new Date(s.first_at).toLocaleTimeString()}–${new Date(s.last_at).toLocaleTimeString()} · ${s.count} reply`,
          }))}
          disabled={sessions.length === 0}
        />
        <Popconfirm
          title="Xóa toàn bộ log của session này?"
          okText="Xóa"
          cancelText="Hủy"
          onConfirm={handleClear}
          disabled={selectedSessionId === null}
        >
          <Button danger icon={<DeleteOutlined />} disabled={selectedSessionId === null}>
            Clear session
          </Button>
        </Popconfirm>
      </Space>

      <div style={{ maxHeight: 500, overflowY: "auto" }}>
        {logs.length === 0 ? (
          <Text type="secondary">Chưa có reply log nào</Text>
        ) : (
          logs.map((log) => <ReplyLogRow key={log.id} log={log} />)
        )}
      </div>
    </div>
  );
}
