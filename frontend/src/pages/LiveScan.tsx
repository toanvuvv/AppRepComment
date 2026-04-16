import { useState, useEffect, useRef, useCallback } from "react";
import {
  Card,
  Button,
  Input,
  Avatar,
  Row,
  Col,
  Table,
  Alert,
  Badge,
  Tag,
  Space,
  Typography,
  Popconfirm,
  message,
  Divider,
  Switch,
  Select,
  Modal,
} from "antd";
import {
  UserOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  InfoCircleOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useReplyLogs } from "../hooks/useReplyLogs";
import type { ReplyLog, ReplyOutcome } from "../api/replyLogs";
import {
  type NickLive,
  type LiveSession,
  type CommentItem,
  type ModeratorStatus,
  type ModeratorReplyResult,
  listNickLives,
  createNickLive,
  deleteNickLive,
  getSessions,
  startScan,
  stopScan,
  getScanStatus,
  saveModeratorCurl,
  getModeratorStatus,
  removeModerator,
  sendModeratorReply,
  autoReplyComments,
} from "../api/nickLive";
import {
  type NickLiveSettings,
  type NickLiveSettingsUpdate,
  type ReplyMode,
  getNickLiveSettings,
  updateNickLiveSettings,
} from "../api/settings";
import KnowledgeProductsCard from "../components/KnowledgeProductsCard";
import CommentFeed from "../components/CommentFeed";
import NickConfigModal from "../components/NickConfigModal";

const { Title, Text } = Typography;
const { TextArea } = Input;

function formatDateTime(ts?: number): string {
  if (!ts) return "";
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleString("vi-VN");
}

function getDisplayName(c: CommentItem): string {
  return c.userName || c.username || c.nick_name || c.nickname || "Unknown";
}

function getCommentText(c: CommentItem): string {
  return c.content || c.comment || c.message || c.msg || "";
}

const OUTCOME_COLOR: Record<ReplyOutcome, string> = {
  success: "green",
  failed: "red",
  dropped: "orange",
  circuit_open: "volcano",
  no_config: "default",
};

const REPLY_MODE_LABEL: Record<ReplyMode, string> = {
  none: "None",
  knowledge: "Knowledge AI",
  ai: "AI thường",
  template: "Template",
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
    <div
      style={{
        padding: "4px 0",
        borderBottom: "1px solid #f0f0f0",
        fontSize: 13,
      }}
    >
      <Space size={6} wrap>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {time}
        </Text>
        <Tag color={OUTCOME_COLOR[log.outcome]}>
          {OUTCOME_LABEL[log.outcome] ?? log.outcome}
        </Tag>
        {log.reply_type && <Tag>{log.reply_type}</Tag>}
        {log.cached_hit && <Tag color="cyan">cache</Tag>}
        {log.latency_ms !== null && (
          <Tag color="geekblue">{log.latency_ms}ms</Tag>
        )}
        <Text strong style={{ color: "#1677ff" }}>
          @{log.guest_name || log.guest_id || "?"}
        </Text>
        {log.comment_text && (
          <Text type="secondary" ellipsis style={{ maxWidth: 220 }}>
            "{log.comment_text}"
          </Text>
        )}
        {detail && (
          <Text
            ellipsis
            style={{
              maxWidth: 320,
              color: log.outcome === "success" ? "#389e0d" : "#cf1322",
            }}
          >
            → {detail}
          </Text>
        )}
      </Space>
    </div>
  );
}

function LiveScan() {
  const [nickLives, setNickLives] = useState<NickLive[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [jsonInput, setJsonInput] = useState("");
  const [addLoading, setAddLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  const [activeSession, setActiveSession] = useState<LiveSession | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);

  // Moderator state
  const [curlInput, setCurlInput] = useState("");
  const [curlLoading, setCurlLoading] = useState(false);
  const [modStatus, setModStatus] = useState<ModeratorStatus | null>(null);
  const [replyText, setReplyText] = useState("");
  const [replyLoading, setReplyLoading] = useState(false);
  const [replyResults, setReplyResults] = useState<ModeratorReplyResult[]>([]);
  const [nickSettings, setNickSettings] = useState<NickLiveSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);

  // Nick config modal
  const [configNick, setConfigNick] = useState<{ id: number; name: string } | null>(null);

  // Knowledge Products modal
  const [knowledgeModalOpen, setKnowledgeModalOpen] = useState(false);

  // Reply Logs modal
  const [replyLogsModalOpen, setReplyLogsModalOpen] = useState(false);

  // Reply logs (polled while scanning)
  const { logs: replyLogs, stats: replyStats, index: replyLogIndex, refresh: refreshReplyLogs } =
    useReplyLogs(selectedId, isScanning);

  // Ref for comments from CommentFeed (no re-renders)
  const commentsRef = useRef<CommentItem[]>([]);

  const handleCommentsChange = useCallback((comments: CommentItem[]) => {
    commentsRef.current = comments;
  }, []);

  const loadNickLives = useCallback(async () => {
    try {
      const data = await listNickLives();
      setNickLives(data);
    } catch {
      message.error("Không thể tải danh sách nick live");
    }
  }, []);

  useEffect(() => {
    loadNickLives();
  }, [loadNickLives]);

  // Auto-check sessions + detect scanning state on nick selection
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;

    async function autoCheck() {
      // Check sessions
      setSessionsLoading(true);
      try {
        const data = await getSessions(selectedId!);
        if (!cancelled) {
          setSessions(data.sessions);
          setActiveSession(data.active_session);
        }
      } catch {
        // ignore
      } finally {
        if (!cancelled) setSessionsLoading(false);
      }

      // Check scan state
      try {
        const status = await getScanStatus(selectedId!);
        if (!cancelled && status.is_scanning) {
          setIsScanning(true);
        }
      } catch {
        // Not scanning or error — ignore
      }
    }

    autoCheck();
    return () => { cancelled = true; };
  }, [selectedId]);

  const handleAdd = useCallback(async () => {
    if (!jsonInput.trim()) {
      message.error("Vui lòng nhập JSON");
      return;
    }
    try {
      const parsed = JSON.parse(jsonInput);
      if (!parsed.user || !parsed.cookies) {
        message.error("JSON phải có trường 'user' và 'cookies'");
        return;
      }
      setAddLoading(true);
      await createNickLive({ user: parsed.user, cookies: parsed.cookies });
      message.success("Thêm nick live thành công");
      setJsonInput("");
      await loadNickLives();
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        message.error("JSON không hợp lệ");
      } else {
        message.error("Không thể thêm nick live");
      }
    } finally {
      setAddLoading(false);
    }
  }, [jsonInput, loadNickLives]);

  const handleDelete = useCallback(
    async (id: number) => {
      try {
        await deleteNickLive(id);
        message.success("Đã xóa nick live");
        if (selectedId === id) {
          setSelectedId(null);
          setSessions([]);
          setActiveSession(null);
          setIsScanning(false);
        }
        await loadNickLives();
      } catch {
        message.error("Không thể xóa nick live");
      }
    },
    [selectedId, loadNickLives]
  );

  const handleCheckSessions = useCallback(async () => {
    if (!selectedId) return;
    setSessionsLoading(true);
    try {
      const data = await getSessions(selectedId);
      setSessions(data.sessions);
      setActiveSession(data.active_session);
    } catch {
      message.error("Không thể kiểm tra phiên live");
    } finally {
      setSessionsLoading(false);
    }
  }, [selectedId]);

  const handleStartScan = useCallback(async () => {
    if (!selectedId || !activeSession) return;
    setScanLoading(true);
    try {
      await startScan(selectedId, activeSession.sessionId);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail !== "Already scanning") {
        message.error("Không thể bắt đầu quét");
        setScanLoading(false);
        return;
      }
    }
    setIsScanning(true);
    message.success("Bắt đầu quét comment");
    setScanLoading(false);
  }, [selectedId, activeSession]);

  const handleStopScan = useCallback(async () => {
    if (!selectedId) return;
    try {
      await stopScan(selectedId);
      setIsScanning(false);
      message.success("Đã dừng quét comment");
    } catch {
      message.error("Không thể dừng quét");
    }
  }, [selectedId]);

  // --- Moderator handlers ---

  const loadModStatus = useCallback(async () => {
    if (!selectedId) return;
    try {
      const status = await getModeratorStatus(selectedId);
      setModStatus(status);
    } catch {
      setModStatus(null);
    }
  }, [selectedId]);

  const loadNickSettings = useCallback(async () => {
    if (!selectedId) return;
    try {
      const s = await getNickLiveSettings(selectedId);
      setNickSettings(s);
    } catch {
      setNickSettings(null);
    }
  }, [selectedId]);

  useEffect(() => {
    if (selectedId) {
      loadModStatus();
      loadNickSettings();
    } else {
      setModStatus(null);
      setNickSettings(null);
    }
  }, [selectedId, loadModStatus, loadNickSettings]);

  const handleUpdateNickSettings = useCallback(
    async (patch: NickLiveSettingsUpdate) => {
      if (!selectedId) return;
      setSettingsLoading(true);
      try {
        const updated = await updateNickLiveSettings(selectedId, patch);
        setNickSettings(updated);
        message.success("Đã cập nhật");
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail;
        message.error(detail || "Cập nhật thất bại");
      } finally {
        setSettingsLoading(false);
      }
    },
    [selectedId]
  );

  const handleSaveCurl = useCallback(async () => {
    if (!selectedId || !curlInput.trim()) {
      message.error("Vui lòng dán cURL moderator");
      return;
    }
    setCurlLoading(true);
    try {
      await saveModeratorCurl(selectedId, curlInput);
      message.success("Lưu cURL moderator thành công");
      setCurlInput("");
      await loadModStatus();
    } catch {
      message.error("Không thể parse cURL");
    } finally {
      setCurlLoading(false);
    }
  }, [selectedId, curlInput, loadModStatus]);

  const handleRemoveModerator = useCallback(async () => {
    if (!selectedId) return;
    try {
      await removeModerator(selectedId);
      message.success("Đã xóa moderator");
      await loadModStatus();
    } catch {
      message.error("Không thể xóa moderator");
    }
  }, [selectedId, loadModStatus]);

  const handleSendReply = useCallback(
    async (comment: CommentItem) => {
      if (!selectedId || !replyText.trim()) {
        message.error("Nhập nội dung reply");
        return;
      }
      const guestName = getDisplayName(comment);
      const guestId = comment.streamerId || comment.userId || comment.user_id || comment.uid || 0;
      setReplyLoading(true);
      try {
        const result = await sendModeratorReply(selectedId, guestName, guestId, replyText);
        if (result.success) {
          message.success(`Đã reply @${guestName}`);
        } else {
          message.error(`Reply thất bại: ${result.error || result.response || "Unknown error"}`);
        }
        setReplyResults((prev) => [...prev, result].slice(-100));
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        message.error(detail || "Không thể gửi reply");
      } finally {
        setReplyLoading(false);
      }
    },
    [selectedId, replyText]
  );

  const handleAutoReply = useCallback(async () => {
    const currentComments = commentsRef.current;
    if (!selectedId || !replyText.trim() || currentComments.length === 0) {
      message.error("Cần nội dung reply và comments");
      return;
    }
    setReplyLoading(true);
    try {
      const results = await autoReplyComments(selectedId, currentComments, replyText);
      const successCount = results.filter((r) => r.success).length;
      message.success(`Đã reply ${successCount}/${results.length} comment`);
      setReplyResults(results);
    } catch {
      message.error("Auto reply thất bại");
    } finally {
      setReplyLoading(false);
    }
  }, [selectedId, replyText]);

  const sessionColumns: ColumnsType<LiveSession> = [
    { title: "Session ID", dataIndex: "sessionId", key: "sessionId", width: 100 },
    { title: "Tiêu đề", dataIndex: "title", key: "title", ellipsis: true },
    {
      title: "Bắt đầu",
      dataIndex: "startTime",
      key: "startTime",
      render: (v: number) => formatDateTime(v),
      width: 180,
    },
    {
      title: "Trạng thái",
      dataIndex: "status",
      key: "status",
      render: (v: number) =>
        v === 1 ? <Tag color="green">Đang live</Tag> : <Tag>Kết thúc</Tag>,
      width: 100,
    },
    { title: "Lượt xem", dataIndex: "views", key: "views", width: 100 },
    { title: "Người xem", dataIndex: "viewers", key: "viewers", width: 100 },
    { title: "Comment", dataIndex: "comments", key: "comments", width: 100 },
  ];

  return (
    <div>
      <Title level={3}>Quét Comment Live Shopee</Title>

      {/* Section 1: Add NickLive */}
      <Card title="Thêm Nick Live" style={{ marginBottom: 16 }}>
        <TextArea
          rows={4}
          placeholder='Dán JSON vào đây, ví dụ: {"user": {...}, "cookies": "..."}'
          value={jsonInput}
          onChange={(e) => setJsonInput(e.target.value)}
        />
        <Button
          type="primary"
          onClick={handleAdd}
          loading={addLoading}
          style={{ marginTop: 8 }}
        >
          Thêm
        </Button>
      </Card>

      {/* Section 2: NickLive List */}
      <Card title="Danh sách Nick Live" style={{ marginBottom: 16 }}>
        {nickLives.length === 0 ? (
          <Text type="secondary">Chưa có nick live nào</Text>
        ) : (
          <Row gutter={[12, 12]}>
            {nickLives.map((nl) => (
              <Col key={nl.id} xs={24} sm={12} md={8} lg={6}>
                <Card
                  hoverable
                  size="small"
                  onClick={() => {
                    setSelectedId(nl.id);
                    setSessions([]);
                    setActiveSession(null);
                    setIsScanning(false);
                    setModStatus(null);
                    setReplyResults([]);
                  }}
                  style={{
                    border:
                      selectedId === nl.id
                        ? "2px solid #1677ff"
                        : "1px solid #d9d9d9",
                  }}
                  actions={[
                    <Button
                      key="config"
                      size="small"
                      icon={<SettingOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfigNick({ id: nl.id, name: nl.name });
                      }}
                    />,
                    <Popconfirm
                      key="delete"
                      title="Xác nhận xóa nick live này?"
                      onConfirm={(e) => {
                        e?.stopPropagation();
                        handleDelete(nl.id);
                      }}
                      onCancel={(e) => e?.stopPropagation()}
                    >
                      <Button
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        size="small"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Xóa
                      </Button>
                    </Popconfirm>,
                  ]}
                >
                  <Card.Meta
                    avatar={
                      <Avatar
                        src={nl.avatar}
                        icon={!nl.avatar ? <UserOutlined /> : undefined}
                      />
                    }
                    title={nl.name}
                    description={`User ID: ${nl.user_id}`}
                  />
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* Section 3: Live Sessions */}
      {selectedId && (
        <Card title="Phiên Live" style={{ marginBottom: 16 }}>
          <Button
            icon={<ReloadOutlined />}
            onClick={handleCheckSessions}
            loading={sessionsLoading}
          >
            Kiểm tra phiên live
          </Button>

          <Divider />

          {activeSession ? (
            <Card
              type="inner"
              title={
                <Space>
                  <Badge status="processing" />
                  <span>Phiên live đang hoạt động</span>
                </Space>
              }
              style={{
                marginBottom: 16,
                borderColor: "#52c41a",
              }}
            >
              <Space direction="vertical" size="small">
                <Text strong>
                  {activeSession.title || `Session #${activeSession.sessionId}`}
                </Text>
                <Text>Session ID: {activeSession.sessionId}</Text>
                <Text>
                  Bắt đầu: {formatDateTime(activeSession.startTime)}
                </Text>
                <Space>
                  <Tag color="blue">
                    Lượt xem: {activeSession.views}
                  </Tag>
                  <Tag color="cyan">
                    Đang xem: {activeSession.viewers}
                  </Tag>
                  <Tag color="purple">
                    Đỉnh: {activeSession.peakViewers}
                  </Tag>
                </Space>
              </Space>
              <div style={{ marginTop: 12 }}>
                <Button
                  type="primary"
                  size="large"
                  icon={<PlayCircleOutlined />}
                  onClick={handleStartScan}
                  loading={scanLoading}
                  disabled={isScanning}
                  style={{ backgroundColor: "#52c41a", borderColor: "#52c41a" }}
                >
                  Bắt đầu quét comment
                </Button>
              </div>
            </Card>
          ) : (
            sessions.length > 0 && (
              <Alert
                type="warning"
                message="Không có phiên live nào đang hoạt động"
                style={{ marginBottom: 16 }}
                showIcon
              />
            )
          )}

          {sessions.length > 0 && (
            <Table
              dataSource={sessions}
              columns={sessionColumns}
              rowKey="sessionId"
              size="small"
              pagination={false}
              scroll={{ x: 800 }}
            />
          )}
        </Card>
      )}

      {/* Section 4: Comment Feed (SSE-powered) */}
      <CommentFeed
        nickLiveId={selectedId}
        isScanning={isScanning}
        onStopScan={handleStopScan}
        onCommentsChange={handleCommentsChange}
        replyLogIndex={replyLogIndex}
      />

      {/* Section 4b: Reply Logs summary */}
      {selectedId && isScanning && (
        <Card
          size="small"
          style={{ marginTop: 16 }}
          title={
            <Space wrap>
              <span>Reply Logs (24h)</span>
              {replyStats && (
                <>
                  <Tag color="blue">Tổng: {replyStats.total}</Tag>
                  <Tag color="green">OK: {replyStats.success}</Tag>
                  <Tag color="red">Fail: {replyStats.failed}</Tag>
                  <Tag color="orange">Dropped: {replyStats.dropped}</Tag>
                  <Tag color="volcano">Circuit: {replyStats.circuit_open}</Tag>
                  <Tag>
                    Success rate:{" "}
                    {(replyStats.success_rate * 100).toFixed(1)}%
                  </Tag>
                  {replyStats.p50_latency_ms !== null && (
                    <Tag color="geekblue">
                      p50 {replyStats.p50_latency_ms}ms / p95{" "}
                      {replyStats.p95_latency_ms}ms
                    </Tag>
                  )}
                </>
              )}
            </Space>
          }
          extra={
            <Space>
              <Button size="small" onClick={refreshReplyLogs}>
                <ReloadOutlined /> Refresh
              </Button>
              <Button
                size="small"
                icon={<FileTextOutlined />}
                onClick={() => setReplyLogsModalOpen(true)}
              >
                Xem tất cả
              </Button>
            </Space>
          }
        >
          {replyLogs.length === 0 ? (
            <Text type="secondary">Chưa có reply log nào</Text>
          ) : (
            <div style={{ maxHeight: 220, overflowY: "auto" }}>
              {replyLogs.slice(0, 20).map((log) => (
                <ReplyLogRow key={log.id} log={log} />
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Reply Logs Modal */}
      <Modal
        title="Tất cả Reply Logs"
        open={replyLogsModalOpen}
        onCancel={() => setReplyLogsModalOpen(false)}
        footer={null}
        width={900}
      >
        <div style={{ maxHeight: "70vh", overflowY: "auto" }}>
          {replyLogs.length === 0 ? (
            <Text type="secondary">Chưa có reply log nào</Text>
          ) : (
            replyLogs.map((log) => <ReplyLogRow key={log.id} log={log} />)
          )}
        </div>
      </Modal>

      {/* Section 5: Moderator - only when nick selected */}
      {selectedId && (
        <>
          <Divider />
          <Title level={4}>Moderator - Reply Comment</Title>

          {!activeSession ? (
            <Alert
              type="warning"
              message="Không có phiên live đang hoạt động"
              description="Cần có phiên live đang hoạt động để sử dụng moderator. Hãy kiểm tra phiên live trước."
              showIcon
              style={{ marginBottom: 16 }}
            />
          ) : (
            <>
              {/* Save cURL */}
              <Card
                title="Lưu cURL Moderator"
                style={{ marginBottom: 16 }}
                extra={
                  modStatus?.configured ? (
                    <Space>
                      <Tag color="green">Đã cấu hình</Tag>
                      <Tag>Host: {modStatus.host_id || "N/A"}</Tag>
                      <Popconfirm title="Xóa moderator?" onConfirm={handleRemoveModerator}>
                        <Button type="text" danger icon={<DeleteOutlined />} size="small">
                          Xóa
                        </Button>
                      </Popconfirm>
                    </Space>
                  ) : (
                    <Tag color="red">Chưa cấu hình</Tag>
                  )
                }
              >
                <TextArea
                  rows={4}
                  placeholder="Dán cURL moderator vào đây (curl https://live.shopee.vn/api/v1/session/.../message ...)"
                  value={curlInput}
                  onChange={(e) => setCurlInput(e.target.value)}
                />
                <Button
                  type="primary"
                  onClick={handleSaveCurl}
                  loading={curlLoading}
                  style={{ marginTop: 8 }}
                >
                  {modStatus?.configured ? "Cập nhật cURL" : "Lưu cURL"}
                </Button>
              </Card>

              {/* Automation Settings Card */}
              {modStatus?.configured && (
                <Card title="Cài đặt tự động" style={{ marginBottom: 16 }}>
                  <Space direction="vertical" style={{ width: "100%" }} size="middle">
                    <Space align="center">
                      <Text strong>Chế độ reply:</Text>
                      <Select<ReplyMode>
                        style={{ width: 220 }}
                        value={nickSettings?.reply_mode ?? "none"}
                        onChange={(v) => handleUpdateNickSettings({ reply_mode: v })}
                        loading={settingsLoading}
                        options={[
                          { value: "none", label: "None (tắt)" },
                          { value: "knowledge", label: "Knowledge AI" },
                          { value: "ai", label: "AI thường" },
                          { value: "template", label: "Template" },
                        ]}
                      />
                      {!isScanning && (
                        <Tag icon={<InfoCircleOutlined />} color="warning">
                          Cần đang quét
                        </Tag>
                      )}
                    </Space>
                    <Space>
                      <Text>Reply qua Host:</Text>
                      <Switch
                        checked={nickSettings?.reply_to_host ?? false}
                        onChange={(v) => handleUpdateNickSettings({ reply_to_host: v })}
                        loading={settingsLoading}
                      />
                      <Text>Reply qua Moderator:</Text>
                      <Switch
                        checked={nickSettings?.reply_to_moderator ?? false}
                        onChange={(v) => handleUpdateNickSettings({ reply_to_moderator: v })}
                        loading={settingsLoading}
                      />
                    </Space>

                    <Divider style={{ margin: "8px 0" }} />

                    <Space>
                      <Switch
                        checked={nickSettings?.auto_post_enabled ?? false}
                        onChange={(v) => handleUpdateNickSettings({ auto_post_enabled: v })}
                        loading={settingsLoading}
                      />
                      <Text strong>Bật Auto-post (đăng comment theo lịch)</Text>
                    </Space>
                    <Space>
                      <Text>Auto-post qua Host:</Text>
                      <Switch
                        checked={nickSettings?.auto_post_to_host ?? false}
                        onChange={(v) => handleUpdateNickSettings({ auto_post_to_host: v })}
                        loading={settingsLoading}
                      />
                      <Text>Auto-post qua Moderator:</Text>
                      <Switch
                        checked={nickSettings?.auto_post_to_moderator ?? false}
                        onChange={(v) => handleUpdateNickSettings({ auto_post_to_moderator: v })}
                        loading={settingsLoading}
                      />
                    </Space>

                    {nickSettings && nickSettings.reply_mode !== "none" && (
                      <Tag color="gold">
                        Reply: {REPLY_MODE_LABEL[nickSettings.reply_mode]} →{" "}
                        {[
                          nickSettings.reply_to_host ? "Host" : null,
                          nickSettings.reply_to_moderator ? "Moderator" : null,
                        ]
                          .filter(Boolean)
                          .join(" + ") || "chưa chọn kênh"}
                      </Tag>
                    )}
                    {nickSettings?.auto_post_enabled && (
                      <Tag color="green">
                        Auto-post →{" "}
                        {[
                          nickSettings.auto_post_to_host ? "Host" : null,
                          nickSettings.auto_post_to_moderator ? "Moderator" : null,
                        ]
                          .filter(Boolean)
                          .join(" + ") || "chưa chọn kênh"}
                      </Tag>
                    )}
                  </Space>
                </Card>
              )}

              {/* Knowledge Products Modal */}
              {modStatus?.configured && (
                <>
                  <Button
                    icon={<DatabaseOutlined />}
                    onClick={() => setKnowledgeModalOpen(true)}
                    style={{ marginBottom: 16 }}
                  >
                    Knowledge Products
                  </Button>
                  <Modal
                    title="Knowledge Products"
                    open={knowledgeModalOpen}
                    onCancel={() => setKnowledgeModalOpen(false)}
                    footer={null}
                    width={1000}
                    destroyOnClose={false}
                  >
                    <KnowledgeProductsCard nickLiveId={selectedId} />
                  </Modal>
                </>
              )}

              {/* Reply Controls - only when scanning AND moderator configured */}
              {isScanning && modStatus?.configured && (
                <Card title="Reply Comment" style={{ marginBottom: 16 }}>
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Input
                      placeholder="Nội dung reply (VD: Cảm ơn bạn đã hỏi!)"
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      onPressEnter={handleAutoReply}
                    />
                    <Button
                      type="primary"
                      onClick={handleAutoReply}
                      loading={replyLoading}
                      disabled={!replyText.trim()}
                    >
                      Auto Reply tất cả
                    </Button>
                  </Space>

                  {/* Reply per comment */}
                  {replyText.trim() && commentsRef.current.length > 0 && (
                    <div style={{ marginTop: 16, maxHeight: 300, overflowY: "auto" }}>
                      <Text strong>Reply từng comment:</Text>
                      {commentsRef.current.slice(-20).map((c, idx) => (
                        <div
                          key={c.id || idx}
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            padding: "4px 8px",
                            borderBottom: "1px solid #f0f0f0",
                          }}
                        >
                          <div>
                            <Text strong style={{ color: "#1677ff" }}>
                              {getDisplayName(c)}:
                            </Text>{" "}
                            <Text>{getCommentText(c)}</Text>
                          </div>
                          <Button
                            size="small"
                            type="link"
                            loading={replyLoading}
                            onClick={() => handleSendReply(c)}
                          >
                            Reply
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Reply Results */}
                  {replyResults.length > 0 && (
                    <div style={{ marginTop: 16 }}>
                      <Text strong>Kết quả reply:</Text>
                      {replyResults.slice(-10).map((r, idx) => (
                        <div key={idx} style={{ padding: "2px 8px" }}>
                          <Tag color={r.success ? "green" : "red"}>
                            {r.success ? "OK" : "FAIL"}
                          </Tag>
                          <Text>
                            @{r.guest} - {r.success ? r.reply : r.error}
                          </Text>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              )}

              {/* Show message when moderator configured but not scanning */}
              {!isScanning && modStatus?.configured && (
                <Alert
                  type="info"
                  message="Bắt đầu quét comment để sử dụng reply"
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              )}
            </>
          )}
        </>
      )}
      {/* Nick Config Modal */}
      <NickConfigModal
        nickLiveId={configNick?.id ?? 0}
        nickName={configNick?.name ?? ""}
        sessionId={
          configNick?.id === selectedId ? (activeSession?.sessionId ?? 0) : 0
        }
        open={!!configNick}
        onClose={() => setConfigNick(null)}
      />
    </div>
  );
}

export default LiveScan;
