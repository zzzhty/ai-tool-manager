import { desktopApi } from './api';
import { DesktopApp } from './app';
import './styles.css';

const root = document.querySelector<HTMLElement>('#app');
if (root) {
  const app = new DesktopApp(root, desktopApi);
  void app.start();
}
