import { useState } from "react";
import { Input, Modal, Typography, message } from "antd";
import { createNickLive } from "../../api/nickLive";

const { TextArea } = Input;
const { Text } = Typography;

interface AddNickModalProps {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
}

export default function AddNickModal({ open, onClose, onAdded }: AddNickModalProps) {
  const [json, setJson] = useState("");
  const [loading, setLoading] = useState(false);

  const handleOk = async () => {
    if (!json.trim()) {
      message.error("Vui lòng nhập JSON");
      return;
    }
    let parsed: { user?: Record<string, unknown>; cookies?: string };
    try {
      parsed = JSON.parse(json);
    } catch {
      message.error("JSON không hợp lệ");
      return;
    }
    if (!parsed.user || !parsed.cookies) {
      message.error("JSON phải có trường 'user' và 'cookies'");
      return;
    }
    setLoading(true);
    try {
      await createNickLive({ user: parsed.user, cookies: parsed.cookies });
      message.success("Thêm nick live thành công");
      setJson("");
      onAdded();
      onClose();
    } catch (err: unknown) {
      const apiErr = err as { response?: { status?: number; data?: { detail?: string } } };
      if (apiErr.response?.status === 403) {
        message.error(apiErr.response.data?.detail ?? "Vượt quá giới hạn nick");
      } else {
        message.error(apiErr.response?.data?.detail ?? "Không thể thêm nick live");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="Thêm Nick Live"
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={loading}
      okText="Thêm"
      cancelText="Hủy"
    >
      <Text type="secondary">Dán JSON dạng <code>{'{"user":{...},"cookies":"..."}'}</code></Text>
      <TextArea
        rows={6}
        value={json}
        onChange={(e) => setJson(e.target.value)}
        style={{ marginTop: 8, fontFamily: "monospace", fontSize: 12 }}
      />
    </Modal>
  );
}
