import { Button, Modal, Space, Tabs, Tag, Typography } from "antd";
import { StopOutlined } from "@ant-design/icons";
import type { NickLive } from "../../api/nickLive";
import { useReplyLogs } from "../../hooks/useReplyLogs";
import { useLiveScanStore } from "../../stores/liveScanStore";
import CommentFeedView from "./CommentFeedView";
import ReplyLogsPanel from "./ReplyLogsPanel";

const { Title, Text } = Typography;

interface FocusFeedModalProps {
  nick: NickLive | null;
  open: boolean;
  onClose: () => void;
}

export default function FocusFeedModal({ nick, open, onClose }: FocusFeedModalProps) {
  const nickId = nick?.id ?? null;

  const session = useLiveScanStore((s) =>
    nickId !== null ? s.sessionsByNick[nickId]?.active ?? null : null
  );
  const isScanning = useLiveScanStore((s) =>
    nickId !== null ? s.scanningNickIds.has(nickId) : false
  );
  const stopScanFor = useLiveScanStore((s) => s.stopScanFor);

  const { index: replyLogIndex } = useReplyLogs(
    nickId,
    open && nickId !== null,
    null,
  );

  const titleNode = nick ? (
    <Space>
      <Title level={5} style={{ margin: 0 }}>@{nick.name}</Title>
      {session ? (
        <Tag color="success">Session #{session.sessionId}</Tag>
      ) : (
        <Tag>Offline</Tag>
      )}
    </Space>
  ) : null;

  return (
    <Modal
      title={titleNode}
      open={open && nick !== null}
      onCancel={onClose}
      footer={null}
      width="min(1000px, calc(100vw - 16px))"
      styles={{ body: { height: "min(75vh, 720px)", padding: 16, overflow: "auto" } }}
      destroyOnHidden
    >
      {nick && (
        <Tabs
          defaultActiveKey="comments"
          items={[
            {
              key: "comments",
              label: "Comments",
              children: (
                <div>
                  <CommentFeedView nickLiveId={nick.id} replyLogIndex={replyLogIndex} />
                  {isScanning && (
                    <div style={{ marginTop: 12 }}>
                      <Button danger icon={<StopOutlined />} onClick={() => stopScanFor(nick.id)}>
                        Dừng quét
                      </Button>
                    </div>
                  )}
                  {!isScanning && (
                    <Text type="secondary" style={{ display: "block", marginTop: 12 }}>
                      Bật toggle Scan trong bảng để bắt đầu nhận comment.
                    </Text>
                  )}
                </div>
              ),
            },
            {
              key: "logs",
              label: "Reply Logs",
              children: <ReplyLogsPanel nickLiveId={nick.id} active={open} />,
            },
          ]}
        />
      )}
    </Modal>
  );
}
