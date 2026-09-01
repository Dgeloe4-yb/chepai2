<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { http } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const status = ref<string>('—')

onMounted(async () => {
  try {
    const { data } = await http.get<{ status: string }>('/api/health')
    status.value = data.status
  } catch {
    status.value = '不可达'
  }
})
</script>

<template>
  <div class="home">
    <el-card>
      <template #header>系统状态</template>
      <p>后端健康检查：<strong>{{ status }}</strong></p>
      <p>当前账号：{{ auth.user?.username }}（{{ auth.isSuperAdmin ? '超管' : '用户' }}）</p>
      <p class="hint">开发环境下 Vite 会将 <code>/api</code> 代理到 <code>http://38.207.179.218:18080</code>。</p>
    </el-card>
  </div>
</template>

<style scoped>
.home {
  max-width: 720px;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
