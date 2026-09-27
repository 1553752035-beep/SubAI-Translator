import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import styles from '../styles/components.module.css';

const Navigation: React.FC = () => {
  const location = useLocation();

  const navItems = [
    { path: '/', label: '🎬 视频处理', exact: true },
    { path: '/terminology', label: '📚 术语库' },
    { path: '/dashboard', label: '📊 仪表盘' },
  ];

  return (
    <nav className={styles.navigation}>
      <div className={styles.navBrand}>
        <Link to="/">SubAI Translator</Link>
      </div>
      <ul className={styles.navLinks}>
        {navItems.map((item) => {
          const isActive = item.exact
            ? location.pathname === item.path
            : location.pathname.startsWith(item.path);
          
          return (
            <li key={item.path}>
              <Link to={item.path} className={isActive ? styles.active : ''}>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
};

export default Navigation;