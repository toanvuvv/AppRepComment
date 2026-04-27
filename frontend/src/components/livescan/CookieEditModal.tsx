import { useEffect, useState } from "react";
import { Input, Modal, Typography, message } from "antd";
import { getNickLiveCookies, updateNickLiveCookies } from "../../api/nickLive";

const { TextArea } = Input;
const { Text } = Typography;

interface CookieEditModalProps {
  nick: { id: number; name: string } | null;
  onClose: () => void;
  onUpdated: () => void;
}

export default function CookieEditModal({ nick, onClose, onUpdated }: CookieEditModalProps) {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);

  useEffect(() => {
    if (!nick) return;
    let cancelled = false;
    setFetching(true);
    getNickLiveCookies(nick.id)
      .then((c) => { if (!cancelled) setValue(c); })
      .catch(() => { if (!cancelled) message.error("Không tải được cookies"); })
      .finally(() => { if (!cancelled) setFetching(false); });
    return () => { cancelled = true; };
  }, [nick]);

  const handleOk = async () => {
    if (!nick) return;
    const raw = value.trim();
    if (!raw) {
      message.error("Vui lòng nhập cookies");
      return;
    }
    let payload: { cookies: string; user?: Record<string, unknown> };
    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && "cookies" in parsed) {
        if (!parsed.cookies) { message.error("JSON phải có 'cookies'"); return; }
        payload = { cookies: parsed.cookies, user: parsed.user };
      } else {
        payload = { cookies: raw };
      }
    } catch {
      payload = { cookies: raw };
    }
    setLoading(true);
    try {
      await updateNickLiveCookies(nick.id, payload);
      message.success("Đã cập nhật cookies");
      setValue("");
      onUpdated();
      onClose();
    } catch {
      message.error("Không thể cập nhật cookies");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`Cập nhật cookies — ${nick?.name ?? ""}`}
      open={!!nick}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={loading}
      okText="Cập nhật"
      cancelText="Hủy"
    >
      <Text type="secondary">
        Dán cookies thuần hoặc JSON dạng <code>{'{"user":{...},"cookies":"..."}'}</code>
      </Text>
      <TextArea
        rows={8}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={fetching ? "Đang tải..." : "Cookies mới hoặc JSON"}
        disabled={fetching}
        style={{ marginTop: 8, fontFamily: "monospace", fontSize: 12 }}
      />
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 4 }}>
        {fetching ? "Đang tải..." : `Độ dài: ${value.length} ký tự`}
      </Text>
    </Modal>
  );
}
