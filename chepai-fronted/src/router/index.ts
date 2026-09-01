import { createRouter, createWebHistory } from 'vue-router'
import { getStoredToken, getStoredUser } from '@/api/client'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', name: 'home', component: () => import('@/views/HomeView.vue') },
        {
          path: 'sites',
          name: 'sites',
          meta: { super: true },
          component: () => import('@/views/SiteListView.vue'),
        },
        {
          path: 'cameras',
          name: 'cameras',
          meta: { super: true },
          component: () => import('@/views/CameraListView.vue'),
        },
        {
          path: 'rois',
          name: 'rois',
          meta: { super: true },
          component: () => import('@/views/RoiListView.vue'),
        },
        { path: 'alerts', name: 'alerts', component: () => import('@/views/AlertListView.vue') },
        { path: 'boxes', name: 'boxes', component: () => import('@/views/BoxStatusView.vue') },
        { path: 'voice', name: 'voice', component: () => import('@/views/VoiceView.vue') },
        {
          path: 'users',
          name: 'users',
          meta: { super: true },
          component: () => import('@/views/UserListView.vue'),
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.path === '/login') {
    return true
  }
  const token = getStoredToken()
  if (to.meta.requiresAuth && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.super) {
    const user = getStoredUser()
    if (user?.role !== 'SUPER_ADMIN') {
      return { path: '/alerts' }
    }
  }
  return true
})

export default router
