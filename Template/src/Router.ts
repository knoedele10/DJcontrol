import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '@/Pages/Dashboard/DashboardPage.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/settings', name: 'settings', component: () => import('@/Pages/Settings/SettingsPage.vue') },
    { path: '/monitor', name: 'monitor', component: () => import('@/Monitor/MonitorPage.vue') },
  ],
})
