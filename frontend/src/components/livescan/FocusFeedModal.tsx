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
  const session = useLiveScanStore((s) =>
    nick ? s.sessionsByNick[nick.id]?.active ?? null : null
  );
  const isScanning = useLiveScanStore((s) =>
    nick ? s.scanningNickIds.has(nick.id) : false
  );
  const stopScanFor = useLiveScanStore((s) => s.stopScanFor);

  const { index: replyLogIndex } = useReplyLogs(
    nick?.id ?? null,
    open && (isScanning || open),
    null,
  );

  if (!nick) return null;

  const titleNode = (
    <Space>
      <Title level={5} style={{ margin: 0 }}>@{nick.name}</Title>
      {session ? (
        <Tag color="success">Session #{session.sessionId}</Tag>
      ) : (
        <Tag>Offline</Tag>
      )}
    </Space>
  );

  return (
    <Modal
      title={titleNode}
      open={open}
      onCancel={onClose}
      footer={null}
      width={1000}
      bodyStyle={{ height: "75vh", padding: 16, overflow: "auto" }}
      destroyOnClose={false}
    >
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
    </Modal>
  );
}
