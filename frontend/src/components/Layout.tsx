import { Layout, Menu } from "antd";
import { HomeOutlined, CommentOutlined, SettingOutlined } from "@ant-design/icons";
import { Outlet, useNavigate, useLocation } from "react-router-dom";

const { Header, Content, Footer } = Layout;

function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    {
      key: "/",
      icon: <HomeOutlined />,
      label: "Trang chu",
    },
    {
      key: "/live-scan",
      icon: <CommentOutlined />,
      label: "Quet Comment",
    },
    {
      key: "/settings",
      icon: <SettingOutlined />,
      label: "Cai dat AI",
    },
  ];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ display: "flex", alignItems: "center" }}>
        <div
          style={{
            color: "#fff",
            fontSize: 18,
            fontWeight: 600,
            marginRight: 40,
            whiteSpace: "nowrap",
          }}
        >
          App Rep Comment
        </div>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1 }}
        />
      </Header>
      <Content style={{ padding: 24 }}>
        <Outlet />
      </Content>
      <Footer style={{ textAlign: "center" }}>
        App Rep Comment &copy; {new Date().getFullYear()}
      </Footer>
    </Layout>
  );
}

export default AppLayout;
