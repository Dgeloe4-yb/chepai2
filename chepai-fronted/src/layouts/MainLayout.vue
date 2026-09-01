<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, House, Location, Crop, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const activeMenu = computed(() => route.path)
const who = computed(() => auth.user?.displayName || auth.user?.username || '')

onMounted(() => {
  void auth.refresh()
})

async function onLogout() {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="240px" class="aside">
      <div class="brand">充电站视觉监控</div>
      <el-menu :default-active="activeMenu" class="menu" router unique-opened>
        <el-menu-item v-if="auth.isSuperAdmin" index="/">
          <el-icon><House /></el-icon>
          <span>概览</span>
        </el-menu-item>

        <el-sub-menu v-if="auth.isSuperAdmin" index="res">
          <template #title>
            <el-icon><Location /></el-icon>
            <span>资源</span>
          </template>
          <el-menu-item index="/sites">站点</el-menu-item>
          <el-menu-item index="/cameras">相机</el-menu-item>
        </el-sub-menu>

        <el-sub-menu v-if="auth.isSuperAdmin" index="cfg">
          <template #title>
            <el-icon><Crop /></el-icon>
            <span>配置</span>
          </template>
          <el-menu-item index="/rois">ROI 区域</el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="ops">
          <template #title>
            <el-icon><Bell /></el-icon>
            <span>运维</span>
          </template>
          <el-menu-item index="/boxes">工控机状态</el-menu-item>
          <el-menu-item index="/alerts">告警记录</el-menu-item>
          <el-menu-item index="/voice">播报语音</el-menu-item>
        </el-sub-menu>

        <el-menu-item v-if="auth.isSuperAdmin" index="/users">
          <el-icon><User /></el-icon>
          <span>账号与工控机</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="title">{{ auth.isSuperAdmin ? '超管后台' : '用户后台' }}</div>
        <div class="who">
          <span>{{ who }}</span>
          <el-button link type="primary" @click="onLogout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}
.aside {
  border-right: 1px solid var(--el-border-color);
}
.brand {
  padding: 16px 14px;
  font-weight: 600;
  border-bottom: 1px solid var(--el-border-color);
}
.menu {
  border-right: none;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--el-border-color);
}
.title {
  font-size: 14px;
  color: var(--el-text-color-regular);
}
.who {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.main {
  padding: 16px;
}
</style>
