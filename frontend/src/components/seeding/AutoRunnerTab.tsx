import { ReactNode, useState } from "react";
import {
  Button,
  Card,
  Checkbox,
  InputNumber,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  PlayCircleOutlined,
  StopOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useSeedingClones } from "../../hooks/useSeedingClones";
import { useSeedingRuns } from "../../hooks/useSeedingRuns";
import { SeedingLogDrawer } from "./SeedingLogDrawer";
import type { SeedingClone, SeedingRunStatus } from "../../api/seeding";

const { Text } = Typography;

interface AutoRunnerTabProps {
  nickHostDropdown: ReactNode;
  sessionDropdown: ReactNode;
  selectedNickLiveId: number | null;
  selectedShopeeSessionId: number | null;
}

const MIN_INTERVAL_FLOOR = 10;

export function AutoRunnerTab({
  nickHostDropdown,
  sessionDropdown,
  selectedNickLiveId,
  selectedShopeeSessionId,
}: AutoRunnerTabProps) {
  const { clones, revive } = useSeedingClones();
  const { runs, start, stop } = useSeedingRuns();

  const [selectedCloneIds, setSelectedCloneIds] = useState<number[]>([]);
  const [minInterval, setMinInterval] = useState<number>(10);
  const [maxInterval, setMaxInterval] = useState<number>(30);
  const [starting, setStarting] = useState(false);
  const [stoppingId, setStoppingId] = useState<number | null>(null);
  const [revivingId, setRevivingId] = useState<number | null>(null);
  const [drawerSessionId, setDrawerSessionId] = useState<number | null>(null);

  const renderHealthBadge = (c: SeedingClone) => {
    if (c.auto_disabled) {
      return (
        <Tooltip title={c.last_error ?? "auto-disabled"}>
          <Tag color="red">Tắt ({c.consecutive_failures} lỗi)</Tag>
        </Tooltip>
      );
    }
    if (c.consecutive_failures > 0) {
      return (
        <Tooltip title={c.last_error ?? "đang lỗi"}>
          <Tag color="orange">Cảnh báo ({c.consecutive_failures})</Tag>
        </Tooltip>
      );
    }
    if (c.last_status === "success") {
      return <Tag color="green">OK</Tag>;
    }
    return <Tag>Chưa gửi</Tag>;
  };

  const handleRevive = async (id: number) => {
    setRevivingId(id);
    try {
      await revive(id);
      message.success("Đã reset clone");
    } catch {
      message.error("Không reset được");
    } finally {
      setRevivingId(null);
    }
  };

  const handleStart = async () => {
    if (!selectedNickLiveId) {
      message.warning("Vui lòng chọn nick host");
      return;
    }
    if (!selectedShopeeSessionId) {
      message.warning("Vui lòng chọn phiên Shopee");
      return;
    }
    if (selectedCloneIds.length === 0) {
      message.warning("Vui lòng chọn ít nhất một clone");
      return;
    }
    const effectiveMin = Math.max(minInterval, MIN_INTERVAL_FLOOR);
    const effectiveMax = Math.max(maxInterval, effectiveMin);
    if (minInterval > maxInterval) {
      message.warning("Min interval phải nhỏ hơn hoặc bằng max interval");
      return;
    }

    setStarting(true);
    try {
      await start({
        nick_live_id: selectedNickLiveId,
        shopee_session_id: selectedShopeeSessionId,
        clone_ids: selectedCloneIds,
        min_interval_sec: effectiveMin,
        max_interval_sec: effectiveMax,
      });
      message.success("Auto runner đã bắt đầu");
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(`Không thể bắt đầu: ${detail ?? "unknown error"}`);
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async (logSessionId: number) => {
    setStoppingId(logSessionId);
    try {
      await stop(logSessionId);
      message.success("Đã dừng auto runner");
    } catch {
      message.error("Không thể dừng auto runner");
    } finally {
      setStoppingId(null);
    }
  };

  const runColumns: ColumnsType<SeedingRunStatus> = [
    {
      title: "Session ID",
      dataIndex: "log_session_id",
      key: "log_session_id",
      width: 100,
    },
    {
      title: "Trạng thái",
      dataIndex: "running",
      key: "running",
      width: 110,
      render: (v: boolean) => (
        <Tag color={v ? "green" : "default"}>{v ? "Đang chạy" : "Dừng"}</Tag>
      ),
    },
    {
      title: "Clone",
      dataIndex: "clone_ids",
      key: "clone_ids",
      render: (ids: number[]) => (
        <Text>{ids.length} clone</Text>
      ),
    },
    {
      title: "Interval (s)",
      key: "interval",
      width: 130,
      render: (_: unknown, record: SeedingRunStatus) => (
        <Text>
          {record.min_interval_sec}–{record.max_interval_sec}s
        </Text>
      ),
    },
    {
      title: "Bắt đầu",
      dataIndex: "started_at",
      key: "started_at",
      width: 160,
      render: (v: string) => (
        <Text style={{ fontSize: 12 }}>
          {new Date(v).toLocaleString("vi-VN")}
        </Text>
      ),
    },
    {
      title: "Hành động",
      key: "actions",
      width: 160,
      render: (_: unknown, record: SeedingRunStatus) => (
        <Space>
          <Button
            danger
            size="small"
            icon={<StopOutlined />}
            loading={stoppingId === record.log_session_id}
            disabled={!record.running}
            onClick={() => handleStop(record.log_session_id)}
          >
            Dừng
          </Button>
          <Button
            size="small"
            icon={<FileTextOutlined />}
            onClick={() => setDrawerSessionId(record.log_session_id)}
          >
            Logs
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="large">
      <Card title="Cấu hình auto runner" size="small">
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Space wrap>
            <div>
              <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                Nick host
              </Text>
              {nickHostDropdown}
            </div>
            <div>
              <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                Phiên Shopee
              </Text>
              {sessionDropdown}
            </div>
          </Space>

          <div>
            <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
              Chọn clones tham gia
            </Text>
            <Space direction="vertical" style={{ width: "100%" }}>
              {clones.map((c) => {
                const checked = selectedCloneIds.includes(c.id);
                return (
                  <Space key={c.id} align="center">
                    <Checkbox
                      checked={checked}
                      disabled={c.auto_disabled}
                      onChange={(e) => {
                        setSelectedCloneIds((prev) =>
                          e.target.checked
                            ? [...prev, c.id]
                            : prev.filter((x) => x !== c.id),
                        );
                      }}
                    >
                      {c.name}
                    </Checkbox>
                    {renderHealthBadge(c)}
                    {(c.auto_disabled || c.consecutive_failures > 0) && (
                      <Button
                        size="small"
                        icon={<ReloadOutlined />}
                        loading={revivingId === c.id}
                        onClick={() => handleRevive(c.id)}
                      >
                        Reset
                      </Button>
                    )}
                  </Space>
                );
              })}
              {clones.length === 0 && (
                <Text type="secondary">Chưa có clone nào</Text>
              )}
            </Space>
          </div>

          <Space align="end" wrap>
            <div>
              <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                Min interval (giây, tối thiểu {MIN_INTERVAL_FLOOR}s)
              </Text>
              <InputNumber
                min={MIN_INTERVAL_FLOOR}
                value={minInterval}
                onChange={(v) => setMinInterval(v ?? MIN_INTERVAL_FLOOR)}
                style={{ width: 140 }}
              />
            </div>
            <div>
              <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                Max interval (giây)
              </Text>
              <InputNumber
                min={minInterval}
                value={maxInterval}
                onChange={(v) => setMaxInterval(v ?? minInterval)}
                style={{ width: 140 }}
              />
            </div>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleStart}
              loading={starting}
              disabled={
                !selectedNickLiveId ||
                !selectedShopeeSessionId ||
                selectedCloneIds.length === 0
              }
            >
              Bắt đầu
            </Button>
          </Space>
        </Space>
      </Card>

      <Card title="Các run đang hoạt động" size="small">
        <Table<SeedingRunStatus>
          dataSource={runs}
          columns={runColumns}
          rowKey="log_session_id"
          size="small"
          pagination={false}
          locale={{ emptyText: "Chưa có run nào đang chạy" }}
        />
      </Card>

      {drawerSessionId !== null && (
        <SeedingLogDrawer
          logSessionId={drawerSessionId}
          onClose={() => setDrawerSessionId(null)}
        />
      )}
    </Space>
  );
}
