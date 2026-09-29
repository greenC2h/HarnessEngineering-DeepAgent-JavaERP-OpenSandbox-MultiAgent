import { createApp } from "vue";

import App from "./App.vue";
import "./styles/main.css";

// 全局样式只在入口处引入，组件负责各自的结构和交互。
createApp(App).mount("#app");
