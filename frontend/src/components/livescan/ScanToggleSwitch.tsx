import { useState } from "react";
import { Switch, message, Tooltip } from "antd";
import { useLiveScanStore } from "../../stores/liveScanStore";

interface ScanToggleSwitchProps {
  nickLiveId: number;
}

export default function ScanToggleSwitch({ nickLiveId }: ScanToggleSwitchProps) {
  const isScanning = useLiveScanStore((s) => s.scanningNickIds.has(nickLiveId));
  const session = useLiveScanStore((s) => s.sessionsByNick[nickLiveId]);
  const cookieExpired = useLiveScanStore((s) => s.cookieExpiredByNick[nickLiveId] ?? false);
  const startScanFor = useLiveScanStore((s) => s.startScanFor);
  const stopScanFor = useLiveScanStore((s) => s.stopScanFor);

  const [loading, setLoading] = useState(false);

  const activeSessionId = session?.active?.sessionId ?? null;
  const isLive = activeSessionId !== null;
  const disabled = !isLive || cookieExpired;

  const tooltip = cookieExpired
    ? "Cookie hết hạn — cập nhật cookies trước"
    : !isLive
    ? "Nick này không đang live"
    : "";

  const handleChange = async (checked: boolean) => {
    if (checked && activeSessionId === null) return;
    setLoading(true);
    try {
      if (checked) {
        await startScanFor(nickLiveId, activeSessionId as number);
        message.success("Bắt đầu quét");
      } else {
        await stopScanFor(nickLiveId);
        message.success("Đã dừng quét");
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Thao tác thất bại";
      message.error(detail);
    } finally {
      setLoading(false);
    }
  };

  const sw = (
    <Switch
      checked={isScanning}
      onChange={handleChange}
      loading={loading}
      disabled={disabled}
    />
  );
  return tooltip ? <Tooltip title={tooltip}>{sw}</Tooltip> : sw;
}
