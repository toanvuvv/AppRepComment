import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, Space, Typography, message } from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  type NickLive,
  deleteNickLive,
  getScanStatus,
  listNickLives,
} from "../api/nickLive";
import NickLiveTable from "../components/livescan/NickLiveTable";
import AddNickModal from "../components/livescan/AddNickModal";
import CookieEditModal from "../components/livescan/CookieEditModal";
import FocusFeedModal from "../components/livescan/FocusFeedModal";
import NickConfigModal from "../components/NickConfigModal";
import { useLiveScanStore } from "../stores/liveScanStore";
import { useNickLiveSessionsPoll } from "../hooks/useNickLiveSessionsPoll";
import { useScanStatsPoll } from "../hooks/useScanStatsPoll";
import ViewAsUserSelect from "../components/livescan/ViewAsUserSelect";
import { useViewAsStore } from "../stores/viewAsStore";

const { Title } = Typography;

function LiveScan() {
  const [nicks, setNicks] = useState<NickLive[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [focusNickId, setFocusNickId] = useState<number | null>(null);
  const [configNick, setConfigNick] = useState<NickLive | null>(null);
  const [editCookieNick, setEditCookieNick] = useState<{ id: number; name: string } | null>(null);

  const setScanning = useLiveScanStore((s) => s.setScanning);
  const openSSE = useLiveScanStore((s) => s.openSSE);
  const stopScanFor = useLiveScanStore((s) => s.stopScanFor);
  const scanningNickIds = useLiveScanStore((s) => s.scanningNickIds);
  const sessionsByNick = useLiveScanStore((s) => s.sessionsByNick);
  const resetAllNickData = useLiveScanStore((s) => s.resetAllNickData);

  const viewAsUserId = useViewAsStore((s) => s.viewAsUserId);

  const handleContextChange = useCallback(() => {
    // Tear down all in-flight SSE / scanning state when switching user context.
    const { sseHandles, closeSSE } = useLiveScanStore.getState();
    Object.keys(sseHandles).forEach((id) => closeSSE(Number(id)));
    setNicks([]);
    setFocusNickId(null);
    setConfigNick(null);
    setEditCookieNick(null);
  }, []);

  const nickIds = useMemo(() => nicks.map((n) => n.id), [nicks]);
  const scanningArray = useMemo(() => Array.from(scanningNickIds), [scanningNickIds]);

  const { forceTick } = useNickLiveSessionsPoll(nickIds, true);
  useScanStatsPoll(scanningArray);

  const loadNicks = useCallback(async () => {
    try {
      const data = await listNickLives();
      setNicks(data);
    } catch {
      message.error("Không thể tải danh sách nick live");
    }
  }, []);

  useEffect(() => { loadNicks(); }, [loadNicks]);

  // When viewAsUserId changes (including being cleared), reload nick list.
  useEffect(() => {
    loadNicks();
    // loadNicks is stable; intentionally omit handleContextChange to avoid double-fire.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewAsUserId]);

  // On first load, restore scanning state from backend for each nick
  useEffect(() => {
    if (nicks.length === 0) return;
    let cancelled = false;
    (async () => {
      for (const n of nicks) {
        try {
          const status = await getScanStatus(n.id);
          if (cancelled) return;
          if (status.is_scanning) {
            setScanning(n.id, true);
            openSSE(n.id);
          }
        } catch { /* ignore */ }
      }
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nicks.length]);

  const handleDelete = useCallback(
    async (id: number) => {
      try {
        if (scanningNickIds.has(id)) await stopScanFor(id);
        await deleteNickLive(id);
        message.success("Đã xóa nick live");
        if (focusNickId === id) setFocusNickId(null);
        await loadNicks();
      } catch {
        message.error("Không thể xóa nick live");
      }
    },
    [scanningNickIds, stopScanFor, focusNickId, loadNicks]
  );

  const focusNick = useMemo(
    () => nicks.find((n) => n.id === focusNickId) ?? null,
    [nicks, focusNickId]
  );

  return (
    <div className="app-page">
      <div className="app-page-title-row">
        <Title level={3} style={{ margin: 0 }}>Quét Comment Live Shopee</Title>
      </div>

      <ViewAsUserSelect onContextChange={handleContextChange} />

      <Card
        style={{ marginBottom: 16 }}
        title="Danh sách Nick Live"
        extra={
          <Space wrap className="app-card-extra-row">
            <Button
              icon={<ReloadOutlined />}
              onClick={() => forceTick()}
              disabled={nicks.length === 0}
            >
              Refresh sessions
            </Button>
            <Button icon={<ReloadOutlined />} onClick={loadNicks}>Refresh</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
              Thêm nick
            </Button>
          </Space>
        }
      >
        <NickLiveTable
          nicks={nicks}
          onFocus={(id) => setFocusNickId(id)}
          onConfig={(n) => setConfigNick(n)}
          onEditCookies={(n) => setEditCookieNick({ id: n.id, name: n.name })}
          onDelete={handleDelete}
        />
      </Card>

      <AddNickModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onAdded={loadNicks}
      />

      <CookieEditModal
        nick={editCookieNick}
        onClose={() => setEditCookieNick(null)}
        onUpdated={loadNicks}
      />

      <FocusFeedModal
        nick={focusNick}
        open={focusNickId !== null}
        onClose={() => setFocusNickId(null)}
      />

      <NickConfigModal
        nickLiveId={configNick?.id ?? 0}
        nickName={configNick?.name ?? ""}
        sessionId={
          configNick ? (sessionsByNick[configNick.id]?.active?.sessionId ?? null) : null
        }
        open={!!configNick}
        onClose={() => setConfigNick(null)}
      />
    </div>
  );
}

export default LiveScan;
