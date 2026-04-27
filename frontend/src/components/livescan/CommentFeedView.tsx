import { useEffect, useRef } from "react";
import { Badge, Card, Space, Spin, Tag, Tooltip, Typography } from "antd";
import type { CommentItem } from "../../api/nickLive";
import type { ReplyLog, ReplyOutcome } from "../../api/replyLogs";
import { buildLogKey, type ReplyLogIndex } from "../../hooks/useReplyLogs";
import { useLiveScanStore } from "../../stores/liveScanStore";

const { Text } = Typography;

const OUTCOME_META: Record<ReplyOutcome, { color: string; label: string }> = {
  success: { color: "green", label: "Đã reply" },
  failed: { color: "red", label: "Reply fail" },
  dropped: { color: "orange", label: "Drop" },
  circuit_open: { color: "volcano", label: "Circuit" },
  no_config: { color: "default", label: "No config" },
};

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

function ReplyStatusTag({ log }: { log: ReplyLog }) {
  const meta = OUTCOME_META[log.outcome] ?? { color: "default", label: log.outcome };
  const tooltip = (
    <div style={{ maxWidth: 360 }}>
      <div><b>Outcome:</b> {log.outcome}</div>
      {log.reply_text && <div><b>Reply:</b> {log.reply_text}</div>}
      {log.error && <div><b>Error:</b> {log.error}</div>}
      {log.latency_ms !== null && <div><b>Latency:</b> {log.latency_ms}ms</div>}
    </div>
  );
  return (
    <Tooltip title={tooltip}>
      <Tag color={meta.color} style={{ marginLeft: 6, cursor: "help" }}>{meta.label}</Tag>
    </Tooltip>
  );
}

function findLog(index: ReplyLogIndex | undefined, c: CommentItem): ReplyLog | undefined {
  if (!index) return undefined;
  const guestId = getGuestId(c);
  const text = getCommentText(c);
  const key = buildLogKey(guestId, text);
  if (key) {
    const hit = index.byCommentKey.get(key);
    if (hit) return hit;
  }
  if (guestId !== undefined && guestId !== 0) return index.byGuest.get(String(guestId));
  return undefined;
}

interface CommentFeedViewProps {
  nickLiveId: number;
  replyLogIndex?: ReplyLogIndex;
}

export default function CommentFeedView({ nickLiveId, replyLogIndex }: CommentFeedViewProps) {
  const comments = useLiveScanStore((s) => s.commentsByNick[nickLiveId] ?? []);
  const isConnected = useLiveScanStore((s) => s.sseConnected[nickLiveId] ?? false);
  const isScanning = useLiveScanStore((s) => s.scanningNickIds.has(nickLiveId));

  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);
  const prevLenRef = useRef(0);

  useEffect(() => {
    const c = scrollRef.current;
    if (!c) return;
    const onScroll = () => {
      const distance = c.scrollHeight - c.scrollTop - c.clientHeight;
      userScrolledUpRef.current = distance > 50;
    };
    c.addEventListener("scroll", onScroll, { passive: true });
    return () => c.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (comments.length !== prevLenRef.current) {
      prevLenRef.current = comments.length;
      if (!userScrolledUpRef.current && scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }
  }, [comments]);

  const title = (
    <Space>
      {isScanning ? <Spin size="small" /> : null}
      <span>{isScanning ? "Đang quét..." : "Đã dừng"}</span>
      <Badge count={comments.length} style={{ backgroundColor: "#52c41a" }} />
      {isScanning && !isConnected && (
        <Text type="secondary" style={{ fontSize: 12 }}>(đang kết nối lại...)</Text>
      )}
    </Space>
  );

  return (
    <Card title={title} bodyStyle={{ padding: 12 }}>
      <div ref={scrollRef} style={{ maxHeight: 500, overflowY: "auto", contain: "layout style" }}>
        {comments.length === 0 ? (
          <Text type="secondary">Chưa có comment nào...</Text>
        ) : (
          comments.map((c, idx) => {
            const ts = formatTs(c.timestamp ?? c.create_time ?? c.ctime);
            const name = getDisplayName(c);
            const text = getCommentText(c);
            const key = c.id ?? `${idx}-${name}-${ts}`;
            const log = findLog(replyLogIndex, c);
            return (
              <div key={key} style={{ padding: "4px 0", borderBottom: "1px solid #f0f0f0" }}>
                {ts && <Text type="secondary" style={{ fontSize: 11, marginRight: 6 }}>{ts}</Text>}
                <Text strong style={{ color: "#1677ff", marginRight: 6 }}>{name}:</Text>
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
