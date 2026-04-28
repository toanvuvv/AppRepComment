import { useState, useEffect, useCallback } from "react";
import { Select, Tabs, Typography } from "antd";
import { listNickLives, getSessions } from "../api/nickLive";
import type { NickLive, LiveSession } from "../api/nickLive";
import { ClonesTab } from "../components/seeding/ClonesTab";
import { TemplatesTab } from "../components/seeding/TemplatesTab";
import { ManualSendTab } from "../components/seeding/ManualSendTab";
import { AutoRunnerTab } from "../components/seeding/AutoRunnerTab";

const { Title } = Typography;

function SeedingPage() {
  const [nickLives, setNickLives] = useState<NickLive[]>([]);
  const [nickLiveId, setNickLiveId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<LiveSession[]>([]);
  const [shopeeSessionId, setShopeeSessionId] = useState<number | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  const loadNickLives = useCallback(async () => {
    try {
      const data = await listNickLives();
      setNickLives(data);
    } catch {
      // silently ignore — user will see empty dropdown
    }
  }, []);

  useEffect(() => {
    loadNickLives();
  }, [loadNickLives]);

  // When nick changes, load its sessions and reset session picker
  useEffect(() => {
    if (nickLiveId === null) {
      setSessions([]);
      setShopeeSessionId(null);
      return;
    }
    let cancelled = false;
    setSessionsLoading(true);
    getSessions(nickLiveId)
      .then((res) => {
        if (!cancelled) {
          setSessions(res.sessions);
          // Auto-select active session when present
          if (res.active_session) {
            setShopeeSessionId(res.active_session.sessionId);
          } else {
            setShopeeSessionId(null);
          }
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSessions([]);
          setShopeeSessionId(null);
        }
      })
      .finally(() => {
        if (!cancelled) setSessionsLoading(false);
      });
    return () => { cancelled = true; };
  }, [nickLiveId]);

  const nickPicker = (
    <Select
      style={{ width: "min(240px, 100%)" }}
      placeholder="Chọn nick host"
      value={nickLiveId}
      onChange={(v) => {
        setNickLiveId(v);
      }}
      options={nickLives.map((nl) => ({ value: nl.id, label: nl.name }))}
      showSearch
      optionFilterProp="label"
      allowClear
      onClear={() => setNickLiveId(null)}
    />
  );

  const sessionPicker = (
    <Select
      style={{ width: "min(240px, 100%)" }}
      placeholder="Chọn phiên Shopee"
      value={shopeeSessionId}
      onChange={setShopeeSessionId}
      options={sessions.map((s) => ({
        value: s.sessionId,
        label: s.title
          ? `#${s.sessionId} — ${s.title}`
          : `#${s.sessionId}`,
      }))}
      loading={sessionsLoading}
      disabled={nickLiveId === null || sessionsLoading}
      allowClear
      onClear={() => setShopeeSessionId(null)}
    />
  );

  return (
    <div>
      <Title level={3}>Seeding</Title>
      <Tabs
        items={[
          {
            key: "clones",
            label: "Clones",
            children: <ClonesTab />,
          },
          {
            key: "templates",
            label: "Templates",
            children: <TemplatesTab />,
          },
          {
            key: "manual",
            label: "Manual Send",
            children: (
              <ManualSendTab
                nickHostDropdown={nickPicker}
                sessionDropdown={sessionPicker}
                selectedNickLiveId={nickLiveId}
                selectedShopeeSessionId={shopeeSessionId}
              />
            ),
          },
          {
            key: "auto",
            label: "Auto Runner",
            children: (
              <AutoRunnerTab
                nickHostDropdown={nickPicker}
                sessionDropdown={sessionPicker}
                selectedNickLiveId={nickLiveId}
                selectedShopeeSessionId={shopeeSessionId}
              />
            ),
          },
        ]}
      />
    </div>
  );
}

export default SeedingPage;
