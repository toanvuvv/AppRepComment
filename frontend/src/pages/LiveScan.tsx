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
  Modal,
} from "antd";
import {
  UserOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  FileTextOutlined,
  SettingOutlined,
  EditOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useReplyLogs } from "../hooks/useReplyLogs";
import type { ReplyLog, ReplyOutcome } from "../api/replyLogs";
import {
  type NickLive,
  type LiveSession,
  type CommentItem,
  listNickLives,
  createNickLive,
  deleteNickLive,
  updateNickLiveCookies,
  getSessions,
  startScan,
  stopScan,
  getScanStatus,
} from "../api/nickLive";
import CommentFeed from "../components/CommentFeed";
import NickConfigModal from "../components/NickConfigModal";

const { Title, Text } = Typography;
const { TextArea } = Input;

function formatDateTime(ts?: number): string {
  if (!ts) return "";
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleString("vi-VN");
}

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

  // Nick config modal
  const [configNick, setConfigNick] = useState<{ id: number; name: string } | null>(null);

  // Update cookies modal
  const [editCookiesNick, setEditCookiesNick] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const [editCookiesJson, setEditCookiesJson] = useState("");
  const [editCookiesLoading, setEditCookiesLoading] = useState(false);

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
        const apiErr = err as { response?: { status?: number; data?: { detail?: string } } };
        if (apiErr.response?.status === 403) {
          message.error(apiErr.response.data?.detail ?? "Không được phép: vượt quá giới hạn nick");
        } else {
          message.error(apiErr.response?.data?.detail ?? "Không thể thêm nick live");
        }
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

  const handleUpdateCookies = useCallback(async () => {
    if (!editCookiesNick) return;
    const raw = editCookiesJson.trim();
    if (!raw) {
      message.error("Vui lòng nhập cookies hoặc JSON");
      return;
    }
    let payload: { cookies: string; user?: Record<string, unknown> };
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && "cookies" in parsed) {
        if (!parsed.cookies) {
          message.error("JSON phải có trường 'cookies'");
          return;
        }
        payload = { cookies: parsed.cookies, user: parsed.user };
      } else {
        payload = { cookies: raw };
      }
    } catch {
      payload = { cookies: raw };
    }
    setEditCookiesLoading(true);
    try {
      await updateNickLiveCookies(editCookiesNick.id, payload);
      message.success("Đã cập nhật cookies");
      setEditCookiesNick(null);
      setEditCookiesJson("");
      await loadNickLives();
    } catch {
      message.error("Không thể cập nhật cookies");
    } finally {
      setEditCookiesLoading(false);
    }
  }, [editCookiesNick, editCookiesJson, loadNickLives]);

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
                    <Button
                      key="edit-cookies"
                      size="small"
                      icon={<EditOutlined />}
                      title="Cập nhật cookies"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditCookiesNick({ id: nl.id, name: nl.name });
                        setEditCookiesJson("");
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

      {/* Update Cookies Modal */}
      <Modal
        title={`Cập nhật cookies — ${editCookiesNick?.name ?? ""}`}
        open={!!editCookiesNick}
        onCancel={() => {
          setEditCookiesNick(null);
          setEditCookiesJson("");
        }}
        onOk={handleUpdateCookies}
        confirmLoading={editCookiesLoading}
        okText="Cập nhật"
        cancelText="Hủy"
      >
        <Text type="secondary">
          Dán cookies mới (chuỗi thuần) hoặc JSON dạng{" "}
          <code>{`{"user":{...},"cookies":"..."}`}</code>. Nếu đang quét,
          scanner sẽ tự khởi động lại với cookies mới.
        </Text>
        <TextArea
          rows={6}
          value={editCookiesJson}
          onChange={(e) => setEditCookiesJson(e.target.value)}
          placeholder="Cookies mới hoặc JSON"
          style={{ marginTop: 8 }}
        />
      </Modal>

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
