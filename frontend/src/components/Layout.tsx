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
    <Layout className="app-shell">
      <Header className="app-header">
        <div className="app-brand">App Rep Comment</div>
        <Menu
          className="app-nav"
          theme="dark"
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
        <Dropdown menu={userMenu} placement="bottomRight" trigger={["click"]}>
          <Space className="app-user-menu">
            <Avatar size="small" icon={<UserOutlined />} />
            <span>{user?.username}</span>
          </Space>
        </Dropdown>
      </Header>
      <Content className="app-content">
        <Outlet />
      </Content>
      <Footer className="app-footer">
        App Rep Comment &copy; {new Date().getFullYear()}
      </Footer>
    </Layout>
  );
}

export default AppLayout;
