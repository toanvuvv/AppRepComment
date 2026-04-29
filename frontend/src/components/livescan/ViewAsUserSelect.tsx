import { useEffect, useState } from "react";
import { Alert, Button, Select, Space, Spin, message } from "antd";
import { useAuth } from "../../contexts/AuthContext";
import { useViewAsStore } from "../../stores/viewAsStore";
import { listUsers, type AdminUser } from "../../api/admin";

interface ViewAsUserSelectProps {
  onContextChange: () => void;
}

export default function ViewAsUserSelect({ onContextChange }: ViewAsUserSelectProps) {
  const { user } = useAuth();
  const viewAsUserId = useViewAsStore((s) => s.viewAsUserId);
  const setViewAsUserId = useViewAsStore((s) => s.setViewAsUserId);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);

  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    setLoading(true);
    listUsers()
      .then((data) => {
        if (!cancelled) setUsers(data);
      })
      .catch(() => {
        if (!cancelled) message.error("Không tải được danh sách user");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  if (!isAdmin || !user) return null;

  const handleChange = (value: number | null) => {
    const next = value === user.id ? null : value;
    setViewAsUserId(next);
    onContextChange();
  };

  const targetUsername =
    viewAsUserId === null
      ? user.username
      : users.find((u) => u.id === viewAsUserId)?.username ?? `user#${viewAsUserId}`;

  return (
    <Space direction="vertical" style={{ width: "100%", marginBottom: 12 }}>
      <Space wrap>
        <span>Đang xem live của:</span>
        <Select
          style={{ minWidth: 240 }}
          value={viewAsUserId ?? user.id}
          onChange={handleChange}
          loading={loading}
          notFoundContent={loading ? <Spin size="small" /> : null}
          options={[
            { value: user.id, label: `${user.username} (chính tôi)` },
            ...users
              .filter((u) => u.id !== user.id)
              .map((u) => ({
                value: u.id,
                label: `${u.username} (${u.nick_count} nicks)`,
              })),
          ]}
        />
        {viewAsUserId !== null && (
          <Button onClick={() => handleChange(null)}>← Về live của tôi</Button>
        )}
      </Space>
      {viewAsUserId !== null && (
        <Alert
          type="warning"
          showIcon
          message={`Bạn đang xem live của ${targetUsername} với quyền admin. Mọi thao tác sẽ được ghi như do ${targetUsername} thực hiện.`}
        />
      )}
    </Space>
  );
}
