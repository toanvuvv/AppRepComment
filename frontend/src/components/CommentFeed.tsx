import { memo, useEffect, useRef } from "react";
import { Badge, Button, Card, Space, Spin, Tag, Tooltip, Typography } from "antd";
import { StopOutlined } from "@ant-design/icons";
import { CommentItem } from "../api/nickLive";
import { useSSEComments } from "../hooks/useSSEComments";
import type { ReplyLog, ReplyOutcome } from "../api/replyLogs";
import { buildLogKey, type ReplyLogIndex } from "../hooks/useReplyLogs";

const { Text } = Typography;

interface CommentFeedProps {
  nickLiveId: number | null;
  isScanning: boolean;
  onStopScan: () => void;
  onCommentsChange?: (comments: CommentItem[]) => void;
  replyLogIndex?: ReplyLogIndex;
}

function formatTs(ts?: number): string {
  if (!ts) return "";
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toLocaleTimeString("vi-VN");
}

function getDisplayName(c: CommentItem): string {
  return c.userName || c.username || c.nick_name || c.nickname || "Unknown";
}

function getCommentText(c: CommentItem): string {
  return c.content || c.comment || c.message || c.msg || "";
}

function getGuestId(c: CommentItem): number | undefined {
  return c.streamerId || c.userId || c.user_id || c.uid;
}

const OUTCOME_META: Record<
  ReplyOutcome,
  { color: string; label: string }
> = {
  success: { color: "green", label: "Đã reply" },
  failed: { color: "red", label: "Reply fail" },
  dropped: { color: "orange", label: "Drop" },
  circuit_open: { color: "volcano", label: "Circuit" },
  no_config: { color: "default", label: "No config" },
};

function ReplyStatusTag({ log }: { log: ReplyLog }) {
  const meta = OUTCOME_META[log.outcome] ?? {
    color: "default",
    label: log.outcome,
  };
  const tooltip = (
    <div style={{ maxWidth: 360 }}>
      <div>
        <b>Outcome:</b> {log.outcome}
      </div>
      {log.reply_type && (
        <div>
          <b>Type:</b> {log.reply_type}
        </div>
      )}
      {log.reply_text && (
        <div>
          <b>Reply:</b> {log.reply_text}
        </div>
      )}
      {log.error && (
        <div>
          <b>Error:</b> {log.error}
        </div>
      )}
      {log.status_code !== null && (
        <div>
          <b>Status:</b> {log.status_code}
        </div>
      )}
      {log.latency_ms !== null && (
        <div>
          <b>Latency:</b> {log.latency_ms}ms
        </div>
      )}
      {log.retry_count > 0 && (
        <div>
          <b>Retry:</b> {log.retry_count}
        </div>
      )}
    </div>
  );
  return (
    <Tooltip title={tooltip}>
      <Tag color={meta.color} style={{ marginLeft: 6, cursor: "help" }}>
        {meta.label}
      </Tag>
    </Tooltip>
  );
}

function findLog(
  index: ReplyLogIndex | undefined,
  c: CommentItem
): ReplyLog | undefined {
  if (!index) return undefined;
  const guestId = getGuestId(c);
  const text = getCommentText(c);
  const key = buildLogKey(guestId, text);
  if (key) {
    const hit = index.byCommentKey.get(key);
    if (hit) return hit;
  }
  if (guestId !== undefined && guestId !== 0) {
    return index.byGuest.get(String(guestId));
  }
  return undefined;
}

function CommentFeedInner({
  nickLiveId,
  isScanning,
  onStopScan,
  onCommentsChange,
  replyLogIndex,
}: CommentFeedProps) {
  const { comments, commentCount, isConnected } = useSSEComments(
    nickLiveId,
    isScanning
  );

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUpRef = useRef(false);
  const prevCommentCountRef = useRef(0);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      isUserScrolledUpRef.current = distanceFromBottom > 50;
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      container.removeEventListener("scroll", handleScroll);
    };
  }, []);

  useEffect(() => {
    if (comments.length !== prevCommentCountRef.current) {
      prevCommentCountRef.current = comments.length;

      if (!isUserScrolledUpRef.current && scrollContainerRef.current) {
        scrollContainerRef.current.scrollTop =
          scrollContainerRef.current.scrollHeight;
      }
    }
  }, [comments]);

  useEffect(() => {
    onCommentsChange?.(comments);
  }, [comments, onCommentsChange]);

  if (!isScanning || !nickLiveId) {
    return null;
  }

  const cardTitle = (
    <Space>
      <Spin size="small" />
      <span>Đang quét...</span>
      <Badge count={commentCount} style={{ backgroundColor: "#52c41a" }} />
      {!isConnected && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          (đang kết nối lại...)
        </Text>
      )}
    </Space>
  );

  const cardExtra = (
    <Button danger icon={<StopOutlined />} onClick={onStopScan}>
      Dừng quét
    </Button>
  );

  return (
    <Card title={cardTitle} extra={cardExtra} style={{ marginTop: 16 }}>
      <div
        ref={scrollContainerRef}
        style={{
          maxHeight: 500,
          overflowY: "auto",
          contain: "layout style",
        }}
      >
        {comments.length === 0 ? (
          <Text type="secondary">Chưa có comment nào...</Text>
        ) : (
          comments.map((c, index) => {
            const ts = formatTs(c.timestamp ?? c.create_time ?? c.ctime);
            const name = getDisplayName(c);
            const text = getCommentText(c);
            const key = c.id ?? `${index}-${name}-${ts}`;
            const log = findLog(replyLogIndex, c);

            return (
              <div
                key={key}
                style={{ padding: "4px 0", borderBottom: "1px solid #f0f0f0" }}
              >
                {ts && (
                  <Text type="secondary" style={{ fontSize: 11, marginRight: 6 }}>
                    {ts}
                  </Text>
                )}
                <Text
                  strong
                  style={{ color: "#1677ff", marginRight: 6 }}
                >
                  {name}:
                </Text>
                <Text>{text}</Text>
                {log && <ReplyStatusTag log={log} />}
              </div>
            );
          })
        )}
      </div>
    </Card>
  );
}

const CommentFeed = memo(CommentFeedInner);
export default CommentFeed;
