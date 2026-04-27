import { Layout, Menu, Dropdown, Avatar, Space } from "antd";
import { CommentOutlined, ExperimentOutlined, SettingOutlined, UserOutlined, LogoutOutlined, KeyOutlined, TeamOutlined } from "@ant-design/icons";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import type { MenuProps } from "antd";
import { useAuth } from "../contexts/AuthContext";

const { Header, Content, Footer } = Layout;

function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const menuItems = [
    {
      key: "/live-scan",
      icon: <CommentOutlined />,
      label: "Quét Comment",
    },
    {
      key: "/seeding",
      icon: <ExperimentOutlined />,
      label: "Seeding",
    },
    {
      key: "/settings",
      icon: <SettingOutlined />,
      label: "Cài đặt AI",
    },
  ];

  const userMenu: MenuProps = {
    items: [
      {
        key: "cp",
        label: "Đổi mật khẩu",
        icon: <KeyOutlined />,
        onClick: () => navigate("/change-password"),
      },
      ...(user?.role === "admin"
        ? [{ key: "admin", label: "Quản lý user", icon: <TeamOutlined />, onClick: () => navigate("/admin/users") }]
        : []),
      { type: "divider" as const, key: "d1" },
      {
        key: "logout",
        label: "Đăng xuất",
        icon: <LogoutOutlined />,
        onClick: () => { logout(); navigate("/login"); },
      },
    ],
  };

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
        <Dropdown menu={userMenu} placement="bottomRight" trigger={["click"]}>
          <Space style={{ cursor: "pointer", marginLeft: 16, color: "#fff" }}>
            <Avatar size="small" icon={<UserOutlined />} />
            <span>{user?.username}</span>
          </Space>
        </Dropdown>
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
