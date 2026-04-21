import { memo, useState } from "react";
import {
  Button,
  Card,
  Input,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  ImportOutlined,
  DatabaseOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { KnowledgeProduct } from "../api/knowledge";
import { useKnowledgeProducts } from "../hooks/useKnowledgeProducts";

const { TextArea } = Input;
const { Text } = Typography;

interface Props {
  nickLiveId: number | null;
}

function KnowledgeProductsCardInner({ nickLiveId }: Props) {
  const [rawJson, setRawJson] = useState("");

  const { products, loading, importLoading, handleImport, handleDeleteAll } =
    useKnowledgeProducts(nickLiveId);

  const onImport = async () => {
    const success = await handleImport(rawJson);
    if (success) setRawJson("");
  };

  const parseKeywords = (raw: string): string[] => {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  const parseJson = (raw: string | null): string[] => {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  };

  const formatPrice = (val: number | null): string => {
    if (val === null) return "-";
    return `${val.toLocaleString("vi-VN")}d`;
  };

  const columns: ColumnsType<KnowledgeProduct> = [
    {
      title: "#",
      dataIndex: "product_order",
      width: 50,
      sorter: (a, b) => a.product_order - b.product_order,
    },
    {
      title: "Tên sản phẩm",
      dataIndex: "name",
      ellipsis: true,
      width: 250,
    },
    {
      title: "Item ID",
      dataIndex: "item_id",
      width: 130,
      render: (val: number, r: KnowledgeProduct) => (
        <a
          href={`https://shopee.vn/product/${r.shop_id}/${val}`}
          target="_blank"
          rel="noreferrer"
          style={{ fontFamily: "monospace", fontSize: 12 }}
        >
          {val}
        </a>
      ),
    },
    {
      title: "Shop ID",
      dataIndex: "shop_id",
      width: 110,
      render: (val: number) => (
        <Text copyable style={{ fontFamily: "monospace", fontSize: 12 }}>
          {val}
        </Text>
      ),
    },
    {
      title: "Keywords",
      dataIndex: "keywords",
      width: 200,
      render: (val: string) =>
        parseKeywords(val).map((kw, i) => (
          <Tag key={i} color="blue" style={{ marginBottom: 2 }}>
            {kw}
          </Tag>
        )),
    },
    {
      title: "Giá",
      width: 150,
      render: (_: unknown, r: KnowledgeProduct) => {
        const price =
          r.price_min === r.price_max
            ? formatPrice(r.price_min)
            : `${formatPrice(r.price_min)} - ${formatPrice(r.price_max)}`;
        return (
          <span>
            {price}
            {r.discount_pct ? (
              <Tag color="red" style={{ marginLeft: 4 }}>
                -{r.discount_pct}%
              </Tag>
            ) : null}
          </span>
        );
      },
    },
    {
      title: "Khuyến mãi",
      width: 180,
      render: (_: unknown, r: KnowledgeProduct) => {
        const vouchers = parseJson(r.voucher_info);
        if (!vouchers.length) return "-";
        return (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
            {vouchers.map((v: string, i: number) => (
              <Tag key={i} color="orange" style={{ marginBottom: 2, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" }}>
                {v}
              </Tag>
            ))}
          </div>
        );
      },
    },
    {
      title: "Tồn kho",
      dataIndex: "stock_qty",
      width: 80,
      render: (val: number | null, r: KnowledgeProduct) => (
        <Tag color={r.in_stock ? "green" : "red"}>
          {r.in_stock ? val ?? "Có" : "Hết"}
        </Tag>
      ),
    },
    {
      title: "Đã bán",
      dataIndex: "sold",
      width: 80,
      render: (val: number | null) => (val ? `${val}+` : "-"),
    },
    {
      title: "Rating",
      dataIndex: "rating",
      width: 80,
      render: (val: number | null, r: KnowledgeProduct) =>
        val ? `${val}/5 (${r.rating_count ?? 0})` : "-",
    },
  ];

  if (!nickLiveId) return null;

  return (
    <Card
      title={
        <Space>
          <DatabaseOutlined />
          <span>Knowledge Products</span>
          <Tag color="blue">{products.length} sản phẩm</Tag>
        </Space>
      }
      style={{ marginBottom: 16 }}
      extra={
        products.length > 0 ? (
          <Popconfirm
            title="Xóa tất cả sản phẩm?"
            onConfirm={handleDeleteAll}
            okText="Xóa"
            cancelText="Hủy"
          >
            <Button danger icon={<DeleteOutlined />} size="small">
              Xóa tất cả
            </Button>
          </Popconfirm>
        ) : null
      }
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <div>
          <Text type="secondary">
            Paste JSON response từ Shopee (data giỏ hàng live) để import sản
            phẩm:
          </Text>
          <TextArea
            rows={4}
            placeholder='{"err_code": 0, "data": {"items": [...]}}'
            value={rawJson}
            onChange={(e) => setRawJson(e.target.value)}
            style={{ marginTop: 8 }}
          />
          <Button
            type="primary"
            icon={<ImportOutlined />}
            onClick={onImport}
            loading={importLoading}
            disabled={!rawJson.trim()}
            style={{ marginTop: 8 }}
          >
            Import sản phẩm
          </Button>
        </div>

        {products.length > 0 && (
          <Table
            dataSource={products}
            columns={columns}
            rowKey="pk"
            size="small"
            pagination={false}
            loading={loading}
            scroll={{ x: 800 }}
          />
        )}
      </Space>
    </Card>
  );
}

const KnowledgeProductsCard = memo(KnowledgeProductsCardInner);
export default KnowledgeProductsCard;
