import { Avatar, Button, Popconfirm, Space, Table, Tag, Tooltip, Typography } from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  UserOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { NickLive } from "../../api/nickLive";
import { useLiveScanStore } from "../../stores/liveScanStore";
import ScanToggleSwitch from "./ScanToggleSwitch";

const { Text } = Typography;

function formatViews(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

interface NickLiveTableProps {
  nicks: NickLive[];
  onFocus: (nickId: number) => void;
  onConfig: (nick: NickLive) => void;
  onEditCookies: (nick: NickLive) => void;
  onTestCookies: (nick: NickLive) => void;
  onDelete: (nickId: number) => void;
}

interface RowData extends NickLive {
  key: number;
}

export default function NickLiveTable({
  nicks,
  onFocus,
  onConfig,
  onEditCookies,
  onTestCookies,
  onDelete,
}: NickLiveTableProps) {
  const sessionsByNick = useLiveScanStore((s) => s.sessionsByNick);
  const scanningNickIds = useLiveScanStore((s) => s.scanningNickIds);
  const miniStatsByNick = useLiveScanStore((s) => s.miniStatsByNick);
  const cookieExpiredByNick = useLiveScanStore((s) => s.cookieExpiredByNick);

  const data: RowData[] = nicks.map((n) => ({ ...n, key: n.id }));

  const columns: ColumnsType<RowData> = [
    {
      title: "Nick",
      key: "nick",
      width: 240,
      ellipsis: true,
      render: (_, r) => (
        <Space>
          <Avatar src={r.avatar} icon={!r.avatar ? <UserOutlined /> : undefined} />
          <div style={{ minWidth: 0, maxWidth: 180 }}>
            <div>
              <Tooltip title={r.name}>
                <Text strong ellipsis style={{ display: "block", maxWidth: 170 }}>{r.name}</Text>
              </Tooltip>
            </div>
            <Text type="secondary" ellipsis style={{ fontSize: 11, display: "block", maxWidth: 170 }}>UID: {r.user_id}</Text>
          </div>
        </Space>
      ),
    },
    {
      title: "Trạng thái",
      key: "status",
      width: 160,
      ellipsis: true,
      render: (_, r) => {
        if (cookieExpiredByNick[r.id]) return <Tag color="warning" style={{ whiteSpace: "nowrap" }}>⚠️ Cookie hết hạn</Tag>;
        const entry = sessionsByNick[r.id];
        if (entry?.error) return <Tooltip title={entry.error}><Tag color="error" style={{ whiteSpace: "nowrap" }}>Lỗi</Tag></Tooltip>;
        if (entry?.active) return <Tag color="success" style={{ whiteSpace: "nowrap" }}>🔴 Đang live</Tag>;
        return <Tag style={{ whiteSpace: "nowrap" }}>⚪ Offline</Tag>;
      },
    },
    {
      title: "Session",
      key: "session",
      width: 120,
      render: (_, r) => {
        const a = sessionsByNick[r.id]?.active;
        if (!a) return <Text type="secondary">—</Text>;
        return (
          <Tooltip title={a.title || `Session #${a.sessionId}`}>
            <Text>#{a.sessionId}</Text>
          </Tooltip>
        );
      },
    },
    {
      title: "Viewers",
      key: "viewers",
      width: 90,
      render: (_, r) => {
        const a = sessionsByNick[r.id]?.active;
        return a ? formatViews(a.viewers) : <Text type="secondary">—</Text>;
      },
    },
    {
      title: "C/R 5'",
      key: "stats",
      width: 110,
      render: (_, r) => {
        if (!scanningNickIds.has(r.id)) return <Text type="secondary">—</Text>;
        const s = miniStatsByNick[r.id];
        if (!s) return <Text type="secondary">…</Text>;
        return (
          <Tooltip title={`+${s.comments_new} comment, ✓${s.replies_ok} reply OK, ✗${s.replies_fail} fail`}>
            <Text>+{s.comments_new}/✓{s.replies_ok}</Text>
          </Tooltip>
        );
      },
    },
    {
      title: "Scan",
      key: "scan",
      width: 80,
      render: (_, r) => (
        <div onClick={(e) => e.stopPropagation()}>
          <ScanToggleSwitch nickLiveId={r.id} />
        </div>
      ),
    },
    {
      title: "",
      key: "actions",
      width: 170,
      render: (_, r) => (
        <Space size={4} onClick={(e) => e.stopPropagation()}>
          <Tooltip title="Cấu hình reply">
            <Button size="small" icon={<SettingOutlined />} onClick={() => onConfig(r)} />
          </Tooltip>
          <Tooltip title="Cập nhật cookies">
            <Button size="small" icon={<EditOutlined />} onClick={() => onEditCookies(r)} />
          </Tooltip>
          <Tooltip title="Kiểm tra cookies">
            <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => onTestCookies(r)} />
          </Tooltip>
          <Popconfirm title="Xóa nick live này?" onConfirm={() => onDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Table<RowData>
      dataSource={data}
      columns={columns}
      pagination={false}
      size="middle"
      scroll={{ x: "max-content" }}
      onRow={(r) => ({
        onClick: () => onFocus(r.id),
        style: {
          cursor: "pointer",
          background: scanningNickIds.has(r.id) ? "#f6ffed" : undefined,
          borderLeft: scanningNickIds.has(r.id) ? "4px solid #52c41a" : undefined,
        },
      })}
      locale={{ emptyText: "Chưa có nick live nào" }}
    />
  );
}
