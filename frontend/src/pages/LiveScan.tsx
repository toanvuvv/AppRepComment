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
  Spin,
  Badge,
  Tag,
  Space,
  Typography,
  Popconfirm,
  message,
  Divider,
} from "antd";
import {
  UserOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  StopOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
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
  getComments,
  saveModeratorCurl,
  getModeratorStatus,
  removeModerator,
  sendModeratorReply,
  autoReplyComments,
} from "../api/nickLive";

const { Title, Text } = Typography;
const { TextArea } = Input;

function formatTs(ts?: number): string {
  if (!ts) return "";
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleTimeString("vi-VN");
}

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

function LiveScan() {
  const [nickLives, setNickLives] = useState<NickLive[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [jsonInput, setJsonInput] = useState("");
  const [addLoading, setAddLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  const [activeSession, setActiveSession] = useState<LiveSession | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [commentCount, setCommentCount] = useState(0);
  const [comments, setComments] = useState<CommentItem[]>([]);
  const [scanLoading, setScanLoading] = useState(false);

  // Moderator state
  const [curlInput, setCurlInput] = useState("");
  const [curlLoading, setCurlLoading] = useState(false);
  const [modStatus, setModStatus] = useState<ModeratorStatus | null>(null);
  const [replyText, setReplyText] = useState("");
  const [replyLoading, setReplyLoading] = useState(false);
  const [replyResults, setReplyResults] = useState<ModeratorReplyResult[]>([]);

  const commentsEndRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const loadNickLives = useCallback(async () => {
    try {
      const data = await listNickLives();
      setNickLives(data);
    } catch {
      message.error("Khong the tai danh sach nick live");
    }
  }, []);

  useEffect(() => {
    loadNickLives();
  }, [loadNickLives]);

  useEffect(() => {
    commentsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [comments]);

  // SSE connection for live comments
  useEffect(() => {
    if (!isScanning || !selectedId) return;

    const url = `/api/nick-lives/${selectedId}/comments/stream`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.addEventListener("comment", (event) => {
      try {
        const data = JSON.parse(event.data) as CommentItem;
        setComments((prev) => [...prev, data]);
        setCommentCount((prev) => prev + 1);
      } catch {
        // ignore parse errors
      }
    });

    es.onerror = () => {
      // SSE reconnects automatically; no action needed
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [isScanning, selectedId]);

  // Poll scan status while scanning
  useEffect(() => {
    if (!isScanning || !selectedId) return;

    const interval = setInterval(async () => {
      try {
        const status = await getScanStatus(selectedId);
        if (!status.is_scanning) {
          setIsScanning(false);
        }
        setCommentCount(status.comment_count);
      } catch {
        // ignore polling errors
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [isScanning, selectedId]);

  const handleAdd = useCallback(async () => {
    if (!jsonInput.trim()) {
      message.error("Vui long nhap JSON");
      return;
    }
    try {
      const parsed = JSON.parse(jsonInput);
      if (!parsed.user || !parsed.cookies) {
        message.error("JSON phai co truong 'user' va 'cookies'");
        return;
      }
      setAddLoading(true);
      await createNickLive({ user: parsed.user, cookies: parsed.cookies });
      message.success("Them nick live thanh cong");
      setJsonInput("");
      await loadNickLives();
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        message.error("JSON khong hop le");
      } else {
        message.error("Khong the them nick live");
      }
    } finally {
      setAddLoading(false);
    }
  }, [jsonInput, loadNickLives]);

  const handleDelete = useCallback(
    async (id: number) => {
      try {
        await deleteNickLive(id);
        message.success("Da xoa nick live");
        if (selectedId === id) {
          setSelectedId(null);
          setSessions([]);
          setActiveSession(null);
          setIsScanning(false);
          setComments([]);
        }
        await loadNickLives();
      } catch {
        message.error("Khong the xoa nick live");
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
      message.error("Khong the kiem tra phien live");
    } finally {
      setSessionsLoading(false);
    }
  }, [selectedId]);

  const handleStartScan = useCallback(async () => {
    if (!selectedId || !activeSession) return;
    setScanLoading(true);
    try {
      await startScan(selectedId, activeSession.sessionId);
      const existing = await getComments(selectedId);
      setComments(existing);
      setIsScanning(true);
      setCommentCount(existing.length);
      message.success("Bat dau quet comment");
    } catch {
      message.error("Khong the bat dau quet");
    } finally {
      setScanLoading(false);
    }
  }, [selectedId, activeSession]);

  const handleStopScan = useCallback(async () => {
    if (!selectedId) return;
    try {
      await stopScan(selectedId);
      setIsScanning(false);
      message.success("Da dung quet comment");
    } catch {
      message.error("Khong the dung quet");
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

  useEffect(() => {
    if (selectedId) {
      loadModStatus();
    } else {
      setModStatus(null);
    }
  }, [selectedId, loadModStatus]);

  const handleSaveCurl = useCallback(async () => {
    if (!selectedId || !curlInput.trim()) {
      message.error("Vui long dan cURL moderator");
      return;
    }
    setCurlLoading(true);
    try {
      await saveModeratorCurl(selectedId, curlInput);
      message.success("Luu cURL moderator thanh cong");
      setCurlInput("");
      await loadModStatus();
    } catch {
      message.error("Khong the parse cURL");
    } finally {
      setCurlLoading(false);
    }
  }, [selectedId, curlInput, loadModStatus]);

  const handleRemoveModerator = useCallback(async () => {
    if (!selectedId) return;
    try {
      await removeModerator(selectedId);
      message.success("Da xoa moderator");
      await loadModStatus();
    } catch {
      message.error("Khong the xoa moderator");
    }
  }, [selectedId, loadModStatus]);

  const handleSendReply = useCallback(
    async (comment: CommentItem) => {
      if (!selectedId || !replyText.trim()) {
        message.error("Nhap noi dung reply");
        return;
      }
      const guestName = getDisplayName(comment);
      const guestId = comment.streamerId || comment.userId || comment.user_id || comment.uid || 0;
      setReplyLoading(true);
      try {
        const result = await sendModeratorReply(selectedId, guestName, guestId, replyText);
        if (result.success) {
          message.success(`Da reply @${guestName}`);
        } else {
          message.error(`Reply that bai: ${result.error || result.response || "Unknown error"}`);
        }
        setReplyResults((prev) => [...prev, result]);
      } catch (err: unknown) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        message.error(detail || "Khong the gui reply");
      } finally {
        setReplyLoading(false);
      }
    },
    [selectedId, replyText]
  );

  const handleAutoReply = useCallback(async () => {
    if (!selectedId || !replyText.trim() || comments.length === 0) {
      message.error("Can noi dung reply va comments");
      return;
    }
    setReplyLoading(true);
    try {
      const results = await autoReplyComments(selectedId, comments, replyText);
      const successCount = results.filter((r) => r.success).length;
      message.success(`Da reply ${successCount}/${results.length} comment`);
      setReplyResults(results);
    } catch {
      message.error("Auto reply that bai");
    } finally {
      setReplyLoading(false);
    }
  }, [selectedId, replyText, comments]);

  const sessionColumns: ColumnsType<LiveSession> = [
    { title: "Session ID", dataIndex: "sessionId", key: "sessionId", width: 100 },
    { title: "Tieu de", dataIndex: "title", key: "title", ellipsis: true },
    {
      title: "Bat dau",
      dataIndex: "startTime",
      key: "startTime",
      render: (v: number) => formatDateTime(v),
      width: 180,
    },
    {
      title: "Trang thai",
      dataIndex: "status",
      key: "status",
      render: (v: number) =>
        v === 1 ? <Tag color="green">Dang live</Tag> : <Tag>Ket thuc</Tag>,
      width: 100,
    },
    { title: "Luot xem", dataIndex: "views", key: "views", width: 100 },
    { title: "Nguoi xem", dataIndex: "viewers", key: "viewers", width: 100 },
    { title: "Comment", dataIndex: "comments", key: "comments", width: 100 },
  ];

  return (
    <div>
      <Title level={3}>Quet Comment Live Shopee</Title>

      {/* Section 1: Add NickLive */}
      <Card title="Them Nick Live" style={{ marginBottom: 16 }}>
        <TextArea
          rows={4}
          placeholder='Dan JSON vao day, vi du: {"user": {...}, "cookies": "..."}'
          value={jsonInput}
          onChange={(e) => setJsonInput(e.target.value)}
        />
        <Button
          type="primary"
          onClick={handleAdd}
          loading={addLoading}
          style={{ marginTop: 8 }}
        >
          Them
        </Button>
      </Card>

      {/* Section 2: NickLive List */}
      <Card title="Danh sach Nick Live" style={{ marginBottom: 16 }}>
        {nickLives.length === 0 ? (
          <Text type="secondary">Chua co nick live nao</Text>
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
                    setComments([]);
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
                    <Popconfirm
                      key="delete"
                      title="Xac nhan xoa nick live nay?"
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
                        Xoa
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
        <Card title="Phien Live" style={{ marginBottom: 16 }}>
          <Button
            icon={<ReloadOutlined />}
            onClick={handleCheckSessions}
            loading={sessionsLoading}
          >
            Kiem tra phien live
          </Button>

          <Divider />

          {activeSession ? (
            <Card
              type="inner"
              title={
                <Space>
                  <Badge status="processing" />
                  <span>Phien live dang hoat dong</span>
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
                  Bat dau: {formatDateTime(activeSession.startTime)}
                </Text>
                <Space>
                  <Tag color="blue">
                    Luot xem: {activeSession.views}
                  </Tag>
                  <Tag color="cyan">
                    Dang xem: {activeSession.viewers}
                  </Tag>
                  <Tag color="purple">
                    Dinh: {activeSession.peakViewers}
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
                  Bat dau quet comment
                </Button>
              </div>
            </Card>
          ) : (
            sessions.length > 0 && (
              <Alert
                type="warning"
                message="Khong co phien live nao dang hoat dong"
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

      {/* Section 4: Comment Feed */}
      {isScanning && selectedId && (
        <Card
          title={
            <Space>
              <Spin size="small" />
              <span>Dang quet...</span>
              <Badge
                count={commentCount}
                overflowCount={99999}
                style={{ backgroundColor: "#52c41a" }}
              />
            </Space>
          }
          extra={
            <Button
              type="primary"
              danger
              icon={<StopOutlined />}
              onClick={handleStopScan}
            >
              Dung quet
            </Button>
          }
        >
          <div
            style={{
              maxHeight: 500,
              overflowY: "auto",
              padding: "8px 0",
            }}
          >
            {comments.length === 0 ? (
              <Text type="secondary">Chua co comment nao...</Text>
            ) : (
              comments.map((c, idx) => (
                <div
                  key={c.id || idx}
                  style={{
                    padding: "6px 12px",
                    borderBottom: "1px solid #f0f0f0",
                    display: "flex",
                    gap: 8,
                    alignItems: "flex-start",
                  }}
                >
                  <Text
                    type="secondary"
                    style={{ fontSize: 12, flexShrink: 0 }}
                  >
                    {formatTs(c.timestamp || c.create_time || c.ctime)}
                  </Text>
                  <Text strong style={{ flexShrink: 0, color: "#1677ff" }}>
                    {getDisplayName(c)}:
                  </Text>
                  <Text>{getCommentText(c)}</Text>
                </div>
              ))
            )}
            <div ref={commentsEndRef} />
          </div>
        </Card>
      )}
      {/* Section 5: Moderator - only when nick selected */}
      {selectedId && (
        <>
          <Divider />
          <Title level={4}>Moderator - Reply Comment</Title>

          {!activeSession ? (
            <Alert
              type="warning"
              message="Khong co phien live dang hoat dong"
              description="Can co phien live dang hoat dong de su dung moderator. Hay kiem tra phien live truoc."
              showIcon
              style={{ marginBottom: 16 }}
            />
          ) : (
            <>
              {/* Save cURL */}
              <Card
                title="Luu cURL Moderator"
                style={{ marginBottom: 16 }}
                extra={
                  modStatus?.configured ? (
                    <Space>
                      <Tag color="green">Da cau hinh</Tag>
                      <Tag>Host: {modStatus.host_id || "N/A"}</Tag>
                      <Popconfirm title="Xoa moderator?" onConfirm={handleRemoveModerator}>
                        <Button type="text" danger icon={<DeleteOutlined />} size="small">
                          Xoa
                        </Button>
                      </Popconfirm>
                    </Space>
                  ) : (
                    <Tag color="red">Chua cau hinh</Tag>
                  )
                }
              >
                <TextArea
                  rows={4}
                  placeholder="Dan cURL moderator vao day (curl https://live.shopee.vn/api/v1/session/.../message ...)"
                  value={curlInput}
                  onChange={(e) => setCurlInput(e.target.value)}
                />
                <Button
                  type="primary"
                  onClick={handleSaveCurl}
                  loading={curlLoading}
                  style={{ marginTop: 8 }}
                >
                  {modStatus?.configured ? "Cap nhat cURL" : "Luu cURL"}
                </Button>
              </Card>

              {/* Reply Controls - only when scanning AND moderator configured */}
              {isScanning && modStatus?.configured && (
                <Card title="Reply Comment" style={{ marginBottom: 16 }}>
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <Input
                      placeholder="Noi dung reply (VD: Cam on ban da hoi!)"
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      onPressEnter={handleAutoReply}
                    />
                    <Button
                      type="primary"
                      onClick={handleAutoReply}
                      loading={replyLoading}
                      disabled={!replyText.trim() || comments.length === 0}
                    >
                      Auto Reply tat ca ({comments.length} comment)
                    </Button>
                  </Space>

                  {/* Reply per comment */}
                  {comments.length > 0 && replyText.trim() && (
                    <div style={{ marginTop: 16, maxHeight: 300, overflowY: "auto" }}>
                      <Text strong>Reply tung comment:</Text>
                      {comments.slice(-20).map((c, idx) => (
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
                      <Text strong>Ket qua reply:</Text>
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
                  message="Bat dau quet comment de su dung reply"
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

export default LiveScan;
