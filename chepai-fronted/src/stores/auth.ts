import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  clearSession,
  fetchMe,
  getStoredToken,
  getStoredUser,
  login as apiLogin,
  logout as apiLogout,
  type AppUser,
} from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getStoredToken())
  const user = ref<AppUser | null>(getStoredUser())

  const isLoggedIn = computed(() => !!token.value)
  const isSuperAdmin = computed(() => user.value?.role === 'SUPER_ADMIN')
  const features = computed(() => user.value?.features ?? [])

  function hasFeature(key: string) {
    if (isSuperAdmin.value) return true
    return features.value.includes(key)
  }

  async function login(username: string, password: string) {
    const data = await apiLogin(username, password)
    token.value = data.token
    user.value = data.user
    return data.user
  }

  async function refresh() {
    if (!token.value) return null
    const me = await fetchMe()
    user.value = me
    return me
  }

  async function logout() {
    await apiLogout()
    token.value = ''
    user.value = null
    clearSession()
  }

  return { token, user, isLoggedIn, isSuperAdmin, features, hasFeature, login, refresh, logout }
})
