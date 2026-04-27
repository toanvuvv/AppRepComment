import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Divider,
  Modal,
  Space,
  Switch,
  Tooltip,
  Typography,
  message,
} from "antd";

import { useSeedingProxies } from "../../hooks/useSeedingProxies";
import { ProxyImportPanel } from "./ProxyImportPanel";
import { ProxyTable } from "./ProxyTable";

const { Title, Text } = Typography;

interface ProxySettingsModalProps {
  open: boolean;
  onClose: () => void;
  cloneCount: number;
  onAfterAssign?: () => void;
}

export function ProxySettingsModal({
  open, onClose, cloneCount, onAfterAssign,
}: ProxySettingsModalProps) {
  const {
    proxies, requireProxy, loading,
    create, update, remove,
    importBulk, assign, setRequireProxy,
  } = useSeedingProxies();

  const [onlyUnassigned, setOnlyUnassigned] = useState(true);
  const [assigning, setAssigning] = useState(false);

  const onAssign = async () => {
    setAssigning(true);
    try {
      const r = await assign({ only_unassigned: onlyUnassigned });
      if (r.reason === "ok") {
        message.success(`Đã gán proxy cho ${r.assigned} clone`);
        onAfterAssign?.();
      } else if (r.reason === "no_proxies") {
        message.warning("Chưa có proxy nào");
      } else if (r.reason === "no_clones") {
        message.warning("Chưa có clone nào");
      } else if (r.reason === "all_assigned") {
        message.info("Tất cả clone đã có proxy");
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "Gán thất bại");
    } finally {
      setAssigning(false);
    }
  };

  const assignDisabled = proxies.length === 0 || cloneCount === 0;
  const tooltip = proxies.length === 0
    ? "Chưa có proxy"
    : cloneCount === 0 ? "Chưa có clone" : "";

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      title="Setting Proxy (Seeding)"
      width={780}
      destroyOnClose
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Space>
          <Switch
            checked={requireProxy}
            onChange={(v) => setRequireProxy(v).catch((e: unknown) =>
              message.error(e instanceof Error ? e.message : "Lưu thất bại"),
            )}
          />
          <Text>Bắt buộc dùng proxy (skip clone không có proxy)</Text>
        </Space>

        <Divider style={{ margin: 0 }} />
        <Title level={5} style={{ margin: 0 }}>Import hàng loạt</Title>
        <ProxyImportPanel
          onImport={(scheme, raw_text) =>
            importBulk({ scheme, raw_text })
          }
        />

        <Divider style={{ margin: 0 }} />
        <ProxyTable
          proxies={proxies}
          loading={loading}
          onCreate={create}
          onUpdate={update}
          onDelete={remove}
        />

        <Divider style={{ margin: 0 }} />
        <Title level={5} style={{ margin: 0 }}>Gán proxy cho clones</Title>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Checkbox
            checked={onlyUnassigned}
            onChange={(e) => setOnlyUnassigned(e.target.checked)}
          >
            Chỉ gán cho clone chưa có proxy
          </Checkbox>
          <Tooltip title={tooltip}>
            <Button
              type="primary"
              onClick={onAssign}
              loading={assigning}
              disabled={assignDisabled}
            >
              Gán xoay vòng
            </Button>
          </Tooltip>
          {proxies.length > 0 && cloneCount > 0 && (
            <Alert
              type="info"
              showIcon
              message={
                `Hiện có ${proxies.length} proxy và ${cloneCount} clone. ` +
                `Sẽ phân bổ theo round-robin (proxy[i mod ${proxies.length}]).`
              }
            />
          )}
        </Space>
      </Space>
    </Modal>
  );
}
