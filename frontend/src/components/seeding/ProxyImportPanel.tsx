import { useState } from "react";
import { Alert, Button, Input, Select, Space, Typography } from "antd";

import type {
  ProxyImportResult,
  ProxyScheme,
} from "../../api/seedingProxy";

const { Text } = Typography;
const { TextArea } = Input;

interface ProxyImportPanelProps {
  onImport: (
    scheme: ProxyScheme,
    rawText: string,
  ) => Promise<ProxyImportResult>;
}

export function ProxyImportPanel({ onImport }: ProxyImportPanelProps) {
  const [scheme, setScheme] = useState<ProxyScheme>("socks5");
  const [rawText, setRawText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ProxyImportResult | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const onSubmit = async () => {
    setBusy(true);
    setErrMsg(null);
    try {
      const r = await onImport(scheme, rawText);
      setResult(r);
      if (r.errors.length === 0) setRawText("");
    } catch (e: unknown) {
      setErrMsg(e instanceof Error ? e.message : "Import thất bại");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Space>
        <Text>Scheme:</Text>
        <Select
          value={scheme}
          onChange={(v) => setScheme(v)}
          style={{ width: 120 }}
          options={[
            { value: "socks5", label: "socks5" },
            { value: "http", label: "http" },
            { value: "https", label: "https" },
          ]}
        />
      </Space>
      <TextArea
        rows={6}
        value={rawText}
        onChange={(e) => setRawText(e.target.value)}
        placeholder="host:port:user:pass (mỗi proxy 1 dòng)"
        style={{ fontFamily: "monospace" }}
      />
      <Button
        type="primary"
        onClick={onSubmit}
        loading={busy}
        disabled={!rawText.trim()}
      >
        Import
      </Button>
      {errMsg && <Alert type="error" message={errMsg} showIcon />}
      {result && (
        <Alert
          type={result.errors.length > 0 ? "warning" : "success"}
          showIcon
          message={
            `Đã thêm ${result.created}, ` +
            `trùng ${result.skipped_duplicates}, ` +
            `lỗi ${result.errors.length}`
          }
          description={
            result.errors.length > 0 ? (
              <ul style={{ marginBottom: 0 }}>
                {result.errors.map((e) => (
                  <li key={e.line}>
                    Dòng {e.line}: <code>{e.raw}</code> ({e.reason})
                  </li>
                ))}
              </ul>
            ) : null
          }
        />
      )}
    </Space>
  );
}
