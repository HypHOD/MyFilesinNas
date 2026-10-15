import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('../pages/Dashboard.vue'),
    },
    {
      path: '/rss',
      name: 'rss',
      component: () => import('../pages/Rss.vue'),
    },
    {
      path: '/bangumi',
      name: 'bangumi',
      component: () => import('../pages/Bangumi.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../pages/Settings.vue'),
    },
  ],
})
