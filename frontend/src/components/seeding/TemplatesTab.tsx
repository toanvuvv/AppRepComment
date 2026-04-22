import { useState } from "react";
import {
  Button,
  Input,
  Space,
  Switch,
  Typography,
  Popconfirm,
  message,
  Alert,
  List,
} from "antd";
import { DeleteOutlined, PlusOutlined, ImportOutlined } from "@ant-design/icons";

import { useSeedingTemplates } from "../../hooks/useSeedingTemplates";
import type { SeedingTemplate } from "../../api/seeding";

const { Title } = Typography;
const { TextArea } = Input;

function getErrorDetail(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Lỗi không xác định";
}

export function TemplatesTab() {
  const { templates, loading, error, create, update, remove, bulkCreate } =
    useSeedingTemplates();

  const [newContent, setNewContent] = useState("");
  const [bulkText, setBulkText] = useState("");
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);

  const onAdd = async () => {
    if (!newContent.trim()) return;
    setAdding(true);
    try {
      await create(newContent.trim());
      message.success("Thêm template thành công");
      setNewContent("");
    } catch (e: unknown) {
      message.error("Thêm template thất bại: " + getErrorDetail(e));
    } finally {
      setAdding(false);
    }
  };

  const onBulkImport = async () => {
    const lines = bulkText
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0) {
      message.warning("Không có dòng nào để import");
      return;
    }
    setImporting(true);
    try {
      await bulkCreate(lines);
      message.success(`Import ${lines.length} template thành công`);
      setBulkText("");
    } catch (e: unknown) {
      message.error("Import thất bại: " + getErrorDetail(e));
    } finally {
      setImporting(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="large">
      <Title level={4} style={{ marginBottom: 0 }}>
        Pool template seeding (dùng chung cho mọi clone / session)
      </Title>

      {error && (
        <Alert type="error" message={error} showIcon closable />
      )}

      <List<SeedingTemplate>
        loading={loading}
        dataSource={templates}
        locale={{ emptyText: "Chưa có template nào" }}
        renderItem={(t) => (
          <List.Item
            key={t.id}
            actions={[
              <Popconfirm
                key="del"
                title="Xoá template này?"
                onConfirm={() =>
                  remove(t.id).catch((e: unknown) =>
                    message.error("Xoá thất bại: " + getErrorDetail(e))
                  )
                }
                okText="Xoá"
                cancelText="Huỷ"
              >
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  size="small"
                />
              </Popconfirm>,
            ]}
          >
            <Space>
              <Switch
                checked={t.enabled}
                size="small"
                onChange={(checked) =>
                  update(t.id, { enabled: checked }).catch((e: unknown) =>
                    message.error(
                      "Cập nhật thất bại: " + getErrorDetail(e)
                    )
                  )
                }
              />
              <Input
                defaultValue={t.content}
                style={{ width: 400 }}
                onBlur={(e) => {
                  const val = e.target.value.trim();
                  if (val !== t.content) {
                    update(t.id, { content: val }).catch((err: unknown) =>
                      message.error(
                        "Cập nhật nội dung thất bại: " + getErrorDetail(err)
                      )
                    );
                  }
                }}
              />
            </Space>
          </List.Item>
        )}
      />

      <div>
        <Title level={5}>Thêm 1 câu</Title>
        <Space>
          <Input
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="Nội dung template mới"
            style={{ width: 400 }}
            onPressEnter={onAdd}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={onAdd}
            loading={adding}
            disabled={!newContent.trim()}
          >
            Thêm
          </Button>
        </Space>
      </div>

      <div>
        <Title level={5}>Bulk import (mỗi dòng 1 câu)</Title>
        <Space direction="vertical" style={{ width: "100%" }}>
          <TextArea
            rows={8}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            placeholder={"Câu 1\nCâu 2\nCâu 3\n..."}
          />
          <Button
            icon={<ImportOutlined />}
            onClick={onBulkImport}
            loading={importing}
            disabled={!bulkText.trim()}
          >
            Import
          </Button>
        </Space>
      </div>
    </Space>
  );
}
