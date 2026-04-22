import { Drawer, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useSeedingLogs } from "../../hooks/useSeedingLogs";
import type { SeedingLog } from "../../api/seeding";
import { useSeedingClones } from "../../hooks/useSeedingClones";

const { Text } = Typography;

interface SeedingLogDrawerProps {
  logSessionId: number;
  onClose: () => void;
}

type LogStatus = SeedingLog["status"];

function statusColor(status: LogStatus): string {
  if (status === "success") return "green";
  if (status === "rate_limited") return "orange";
  return "red";
}

function statusLabel(status: LogStatus): string {
  if (status === "success") return "Thành công";
  if (status === "rate_limited") return "Rate limited";
  return "Thất bại";
}

export function SeedingLogDrawer({ logSessionId, onClose }: SeedingLogDrawerProps) {
  const { logs } = useSeedingLogs(logSessionId);
  const { clones } = useSeedingClones();

  const cloneNameMap = new Map(clones.map((c) => [c.id, c.name]));

  const columns: ColumnsType<SeedingLog> = [
    {
      title: "Thời gian",
      dataIndex: "sent_at",
      key: "sent_at",
      width: 160,
      render: (v: string) => (
        <Text style={{ fontSize: 12 }}>
          {new Date(v).toLocaleString("vi-VN")}
        </Text>
      ),
    },
    {
      title: "Clone",
      dataIndex: "clone_id",
      key: "clone_id",
      width: 140,
      render: (id: number) => (
        <Text>{cloneNameMap.get(id) ?? `#${id}`}</Text>
      ),
    },
    {
      title: "Trạng thái",
      dataIndex: "status",
      key: "status",
      width: 130,
      render: (v: LogStatus) => (
        <Tag color={statusColor(v)}>{statusLabel(v)}</Tag>
      ),
    },
    {
      title: "Nội dung",
      dataIndex: "content",
      key: "content",
      ellipsis: true,
    },
    {
      title: "Lỗi",
      dataIndex: "error",
      key: "error",
      width: 200,
      render: (v: string | null) =>
        v ? (
          <Text type="danger" ellipsis style={{ fontSize: 12 }}>
            {v}
          </Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
  ];

  return (
    <Drawer
      title={`Seeding logs — session #${logSessionId}`}
      open
      onClose={onClose}
      width={860}
      destroyOnClose
    >
      <Table<SeedingLog>
        dataSource={logs}
        columns={columns}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: false }}
        scroll={{ x: 700 }}
      />
    </Drawer>
  );
}
