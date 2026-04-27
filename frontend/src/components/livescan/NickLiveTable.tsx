import { Avatar, Button, Popconfirm, Space, Table, Tag, Tooltip, Typography } from "antd";
import {
  DeleteOutlined,
  EditOutlined,
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
      render: (_, r) => (
        <Space>
          <Avatar src={r.avatar} icon={!r.avatar ? <UserOutlined /> : undefined} />
          <div>
            <div><Text strong>{r.name}</Text></div>
            <Text type="secondary" style={{ fontSize: 11 }}>UID: {r.user_id}</Text>
          </div>
        </Space>
      ),
    },
    {
      title: "Trạng thái",
      key: "status",
      width: 160,
      render: (_, r) => {
        if (cookieExpiredByNick[r.id]) return <Tag color="warning">⚠️ Cookie hết hạn</Tag>;
        const entry = sessionsByNick[r.id];
        if (entry?.error) return <Tooltip title={entry.error}><Tag color="error">Lỗi</Tag></Tooltip>;
        if (entry?.active) return <Tag color="success">🔴 Đang live</Tag>;
        return <Tag>⚪ Offline</Tag>;
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
      width: 130,
      render: (_, r) => (
        <Space size={4} onClick={(e) => e.stopPropagation()}>
          <Tooltip title="Cấu hình reply">
            <Button size="small" icon={<SettingOutlined />} onClick={() => onConfig(r)} />
          </Tooltip>
          <Tooltip title="Cập nhật cookies">
            <Button size="small" icon={<EditOutlined />} onClick={() => onEditCookies(r)} />
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
